"""End-to-end: boot FastAPI orchestrator + connect via Python SDK + drive a turn."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "apps" / "orchestrator"))
sys.path.insert(0, str(ROOT / "packages" / "client_py"))

from dotenv import load_dotenv

load_dotenv(ROOT / "apps" / "orchestrator" / ".env")

import uvicorn
from audvoice_client import AudVoiceClient
from live_smoke import synth_to_pcm  # synthesize input audio


async def run_server(stop: asyncio.Event) -> None:
    config = uvicorn.Config(
        "audvoice.main:app",
        host="127.0.0.1",
        port=8088,
        log_level="warning",
        ws_max_size=32 * 1024 * 1024,
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    await stop.wait()
    server.should_exit = True
    await task


async def main() -> int:
    stop = asyncio.Event()
    server_task = asyncio.create_task(run_server(stop))
    try:
        await asyncio.sleep(0.5)
        # Synthesize 16 kHz PCM input we'll send over the wire
        prompt_pcm = await synth_to_pcm("Say hello in one short sentence.")

        async with AudVoiceClient("http://127.0.0.1:8088", api_key="devkey") as c:
            transcripts: list[str] = []
            replies: list[str] = []
            audio_bytes = 0
            done = asyncio.Event()

            async def consume_events():
                async for ev in c.events():
                    t = ev["type"]
                    if t == "transcript.final":
                        transcripts.append(ev["text"])
                    elif t == "response.text.delta":
                        replies.append(ev["delta"])
                    elif t == "response.done":
                        done.set()
                    elif t == "error":
                        print("[error]", ev)

            async def consume_audio():
                nonlocal audio_bytes
                async for sid, pcm in c.audio():
                    audio_bytes += len(pcm)

            ev_task = asyncio.create_task(consume_events())
            au_task = asyncio.create_task(consume_audio())

            # Send 100 ms chunks
            chunk = 3200
            for i in range(0, len(prompt_pcm), chunk):
                await c.send_audio(prompt_pcm[i : i + chunk])
                await asyncio.sleep(0.05)
            # silence to flush utterance
            await c.send_audio(b"\x00" * (16000 * 2 * 2))

            try:
                await asyncio.wait_for(done.wait(), timeout=30)
            except asyncio.TimeoutError:
                print("TIMEOUT waiting for response.done")

            ev_task.cancel()
            au_task.cancel()

            print("transcripts:", transcripts)
            print("reply text :", "".join(replies))
            print("audio bytes:", audio_bytes)
    finally:
        stop.set()
        await server_task
    return 0


if __name__ == "__main__":
    asyncio.run(main())
