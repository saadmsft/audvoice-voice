"""Tiny async client for the AuDesign Voice service.

Usage:
    async with AudVoiceClient(base_url, api_key) as c:
        await c.update_session(instructions="...", voice="ar-AE-FatimaNeural")
        async for ev in c.events():
            if ev["type"] == "response.audio.delta":
                # Next binary frame from c.audio() corresponds to this chunk
                ...
"""

from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import websockets


@dataclass
class AudVoiceClient:
    base_url: str  # e.g. "http://localhost:8080"
    api_key: str
    session_id: str = ""
    _ws: websockets.WebSocketClientProtocol | None = None
    _audio_q: asyncio.Queue[tuple[int, bytes]] | None = None
    _event_q: asyncio.Queue[dict] | None = None
    _reader_task: asyncio.Task | None = None

    async def __aenter__(self) -> "AudVoiceClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def connect(self) -> None:
        async with httpx.AsyncClient(base_url=self.base_url) as http:
            r = await http.post(
                "/v1/sessions", headers={"X-API-Key": self.api_key}, json={}
            )
            r.raise_for_status()
            data = r.json()
        self.session_id = data["session_id"]
        ws_base = self.base_url.replace("http://", "ws://").replace(
            "https://", "wss://"
        )
        ws_url = f"{ws_base}{data['ws_url']}?token={data['token']}"
        self._ws = await websockets.connect(ws_url, max_size=32 * 1024 * 1024)
        self._audio_q = asyncio.Queue()
        self._event_q = asyncio.Queue()
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        assert self._ws and self._audio_q and self._event_q
        try:
            async for msg in self._ws:
                if isinstance(msg, (bytes, bytearray)):
                    if len(msg) < 4:
                        continue
                    sid = struct.unpack(">I", msg[:4])[0]
                    await self._audio_q.put((sid, bytes(msg[4:])))
                else:
                    try:
                        await self._event_q.put(json.loads(msg))
                    except json.JSONDecodeError:
                        pass
        finally:
            await self._event_q.put({"type": "_closed"})

    # ── send ──
    async def send_audio(self, pcm16_16k: bytes) -> None:
        assert self._ws is not None
        await self._ws.send(pcm16_16k)

    async def send_event(self, event: dict) -> None:
        assert self._ws is not None
        await self._ws.send(json.dumps(event, ensure_ascii=False))

    async def update_session(self, **kwargs) -> None:
        await self.send_event({"type": "session.update", "session": kwargs})

    async def commit_input(self) -> None:
        await self.send_event({"type": "input_audio.commit"})

    async def cancel_response(self) -> None:
        await self.send_event({"type": "response.cancel"})

    async def send_text(self, text: str) -> None:
        await self.send_event(
            {
                "type": "conversation.item.create",
                "item": {"role": "user", "content": text},
            }
        )

    async def send_tool_result(self, call_id: str, output: str) -> None:
        await self.send_event(
            {"type": "tool.result", "call_id": call_id, "output": output}
        )

    # ── receive ──
    async def events(self) -> AsyncIterator[dict]:
        assert self._event_q is not None
        while True:
            ev = await self._event_q.get()
            if ev.get("type") == "_closed":
                return
            yield ev

    async def audio(self) -> AsyncIterator[tuple[int, bytes]]:
        assert self._audio_q is not None
        while True:
            yield await self._audio_q.get()

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
        if self._ws:
            await self._ws.close()
