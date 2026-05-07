"""Per-connection session state machine.

Owns the STT, LLM, and TTS pipes and coordinates barge-in. Talks to the
WebSocket through two callables passed in by the transport layer:

    send_json(event_dict)     # JSON event
    send_bytes(stream_id, pcm)  # binary frame

Audio in is fed via `feed_audio(pcm)`; client control events via `handle_event`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

from . import rag
from .llm import LlmRunner
from .protocol import SessionConfig
from .settings import get_settings
from .stt import SttPipe
from .tts import TtsPipe

log = logging.getLogger(__name__)

SendJson = Callable[[dict[str, Any]], Awaitable[None]]
SendBytes = Callable[[int, bytes], Awaitable[None]]


class State(str, Enum):
    LISTEN = "listen"
    USER_SPEAKING = "user_speaking"
    THINKING = "thinking"
    AGENT_SPEAKING = "agent_speaking"
    CLOSED = "closed"


@dataclass
class Session:
    session_id: str
    tenant_id: str
    send_json: SendJson
    send_bytes: SendBytes
    config: SessionConfig = field(default_factory=SessionConfig)

    state: State = State.LISTEN
    stream_id: int = 0
    _stt: SttPipe | None = None
    _llm: LlmRunner = field(default_factory=LlmRunner)
    _tts: TtsPipe | None = None
    _response_task: asyncio.Task | None = None
    _stt_task: asyncio.Task | None = None
    _pending_tools: dict[str, asyncio.Future] = field(default_factory=dict)

    # ── lifecycle ──
    async def start(self) -> None:
        self._apply_config_defaults()
        self._stt = SttPipe(
            languages=self.config.languages,
            silence_ms=(
                self.config.turn_detection.silence_ms
                if self.config.turn_detection
                else get_settings().default_silence_ms
            ),
        )
        self._stt_task = asyncio.create_task(self._stt_loop(), name="stt-loop")
        await self.send_json(
            {
                "type": "session.created",
                "session_id": self.session_id,
                "model": self._llm.model or get_settings().default_model,
                "voice": self.config.voice or get_settings().default_voice,
            }
        )

    async def close(self) -> None:
        if self.state == State.CLOSED:
            return
        self.state = State.CLOSED
        if self._response_task:
            self._response_task.cancel()
        if self._stt_task:
            self._stt_task.cancel()
        if self._stt:
            await self._stt.close()

    # ── client input ──
    def feed_audio(self, pcm: bytes) -> None:
        if self._stt and self.state != State.CLOSED:
            self._stt.feed(pcm)

    async def handle_event(self, ev: dict[str, Any]) -> None:
        t = ev.get("type")
        if t == "session.update":
            self._merge_config(SessionConfig(**ev.get("session", {})))
        elif t == "input_audio.commit":
            # treat as forced end-of-turn
            await self._on_speech_stopped(force=True)
        elif t == "response.cancel":
            await self._cancel_response("client.cancel")
        elif t == "tool.result":
            fut = self._pending_tools.pop(ev["call_id"], None)
            self._llm.add_tool_result(ev["call_id"], ev.get("output", ""))
            if fut and not fut.done():
                fut.set_result(ev.get("output", ""))
        elif t == "conversation.item.create":
            item = ev.get("item", {})
            role = item.get("role", "user")
            content = item.get("content", "")
            if role == "user":
                self._llm.add_user_text(content)
                await self._start_response()
        else:
            await self.send_json({"type": "error", "code": "unknown_event", "message": str(t)})

    # ── STT loop ──
    async def _stt_loop(self) -> None:
        assert self._stt is not None
        async for ev in self._stt.events():
            try:
                if ev.kind == "speech_started":
                    await self._on_speech_started()
                elif ev.kind == "speech_stopped":
                    await self._on_speech_stopped()
                elif ev.kind == "delta":
                    await self.send_json(
                        {"type": "transcript.delta", "text": ev.text, "language": ev.language}
                    )
                elif ev.kind == "final":
                    await self.send_json(
                        {
                            "type": "transcript.final",
                            "text": ev.text,
                            "languages": [ev.language] if ev.language else [],
                            "duration_ms": ev.duration_ms,
                        }
                    )
                    self._llm.add_user_text(ev.text)
                    await self._start_response()
                elif ev.kind == "error":
                    await self.send_json({"type": "error", "code": "stt_error", "message": ev.text})
            except Exception:
                log.exception("error in stt loop")

    # ── transitions ──
    async def _on_speech_started(self) -> None:
        await self.send_json({"type": "vad.speech_started"})
        if self.state == State.AGENT_SPEAKING:
            await self._barge_in()
        else:
            self.state = State.USER_SPEAKING

    async def _on_speech_stopped(self, force: bool = False) -> None:
        await self.send_json({"type": "vad.speech_stopped"})
        if self.state == State.USER_SPEAKING:
            self.state = State.THINKING  # final transcript will trigger _start_response

    async def _barge_in(self) -> None:
        if not self._tts:
            return
        spoken = self._tts.cancel()
        sid = self.stream_id
        self._llm.truncate_assistant_at(spoken)
        if self._response_task:
            self._response_task.cancel()
        await self.send_json(
            {"type": "barge_in.detected", "stream_id": sid, "spoken_chars": spoken}
        )
        self.state = State.USER_SPEAKING

    # ── response generation ──
    async def _start_response(self) -> None:
        if self.state == State.AGENT_SPEAKING:
            await self._cancel_response("auto.preempt")
        self.state = State.THINKING
        self.stream_id += 1
        self._tts = TtsPipe(voice=self.config.voice)
        self._response_task = asyncio.create_task(
            self._run_response(self.stream_id), name=f"response-{self.stream_id}"
        )

    async def _cancel_response(self, reason: str) -> None:
        if self._tts:
            self._tts.cancel()
        if self._response_task:
            self._response_task.cancel()
        self.state = State.LISTEN

    async def _run_response(self, sid: int) -> None:
        assert self._tts is not None
        try:
            # Optional RAG retrieval based on the latest user message
            if self.config.rag and self._llm.history:
                last_user = next(
                    (m["content"] for m in reversed(self._llm.history) if m["role"] == "user"),
                    None,
                )
                if last_user:
                    passages = await rag.retrieve(
                        last_user,
                        self.config.rag.index_name,
                        self.config.rag.top_k,
                        self.config.rag.semantic_config,
                    )
                    if passages:
                        # Stash into instructions for this turn (non-mutating to history)
                        self._llm.instructions = (
                            self.config.instructions or "You are a helpful voice assistant."
                        ) + rag.format_for_prompt(passages)

            saw_audio = False
            async for d in self._llm.stream():
                if d.kind == "text":
                    await self.send_json(
                        {"type": "response.text.delta", "stream_id": sid, "delta": d.text}
                    )
                    async for pcm in self._tts.feed_text(d.text):
                        if not saw_audio:
                            self.state = State.AGENT_SPEAKING
                            saw_audio = True
                        await self.send_json(
                            {"type": "response.audio.delta", "stream_id": sid, "bytes": len(pcm)}
                        )
                        await self.send_bytes(sid, pcm)
                elif d.kind == "tool_call":
                    await self.send_json(
                        {
                            "type": "tool.call",
                            "call_id": d.tool_call_id,
                            "name": d.tool_name,
                            "arguments": d.tool_args,
                        }
                    )
                    fut: asyncio.Future = asyncio.get_event_loop().create_future()
                    self._pending_tools[d.tool_call_id] = fut
                    # Wait for client tool.result, then loop another model turn
                    await fut
                    # Recurse: continue assistant turn after tool result
                    return await self._run_response(sid)
                elif d.kind == "done":
                    pass

            # Flush remaining buffered text
            async for pcm in self._tts.flush():
                if not saw_audio:
                    self.state = State.AGENT_SPEAKING
                    saw_audio = True
                await self.send_json(
                    {"type": "response.audio.delta", "stream_id": sid, "bytes": len(pcm)}
                )
                await self.send_bytes(sid, pcm)

            await self.send_json({"type": "response.audio.done", "stream_id": sid})
            await self.send_json({"type": "response.done", "stream_id": sid})
        except asyncio.CancelledError:
            log.info("response %d cancelled", sid)
            raise
        except Exception as exc:
            log.exception("response failed")
            await self.send_json({"type": "error", "code": "response_failed", "message": str(exc)})
        finally:
            if self.state != State.CLOSED:
                self.state = State.LISTEN

    # ── config ──
    def _apply_config_defaults(self) -> None:
        s = get_settings()
        if not self.config.voice:
            self.config.voice = s.default_voice
        if not self.config.languages:
            self.config.languages = s.language_list
        if not self.config.model:
            self.config.model = s.default_model
        self._llm.model = self.config.model
        if self.config.instructions:
            self._llm.instructions = self.config.instructions
        if self.config.tools:
            self._llm.tools = self.config.tools
        if self.config.temperature is not None:
            self._llm.temperature = self.config.temperature

    def _merge_config(self, patch: SessionConfig) -> None:
        for field_name, val in patch.model_dump(exclude_none=True).items():
            setattr(self.config, field_name, val)
        self._apply_config_defaults()
