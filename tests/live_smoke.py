"""Live integration smoke test:
1. TTS synthesizes "What is the capital of the UAE?" to PCM (Azure Speech UAE North).
2. Feed that PCM into STT continuous recognition -> get transcript.
3. Send transcript to gpt-4.1 -> stream reply.
4. Synthesize the reply to PCM and report total bytes.

Prints timings. Requires: az login + roles on the AI resource. No API keys.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

# Load .env
from dotenv import load_dotenv  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "apps" / "orchestrator" / ".env")

import sys

sys.path.insert(0, str(ROOT / "apps" / "orchestrator"))

import azure.cognitiveservices.speech as speechsdk
from audvoice import aad
from audvoice.llm import LlmRunner
from audvoice.settings import get_settings
from audvoice.stt import SttPipe


async def synth_to_pcm(text: str, voice: str = "en-US-AvaMultilingualNeural") -> bytes:
    s = get_settings()
    cfg = speechsdk.SpeechConfig(
        auth_token=aad.speech_auth_token(s.azure_speech_resource_id),
        region=s.azure_speech_region,
    )
    cfg.speech_synthesis_voice_name = voice
    # Match STT input: 16 kHz PCM
    cfg.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm
    )
    synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
    loop = asyncio.get_event_loop()
    fut = synth.speak_text_async(text)
    result = await loop.run_in_executor(None, fut.get)
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        raise RuntimeError(
            f"TTS failed: {result.reason} / {result.cancellation_details}"
        )
    return result.audio_data


async def stt_recognize(pcm: bytes) -> str:
    """Push PCM into STT, wait for first final, return text."""
    stt = SttPipe(languages=["en-US", "ar-AE"], silence_ms=500)
    # Feed audio in chunks
    chunk = 3200  # 100 ms @ 16 kHz mono 16-bit
    for i in range(0, len(pcm), chunk):
        stt.feed(pcm[i : i + chunk])
        await asyncio.sleep(0.01)
    # then add 1.5s of silence to trigger end-of-utterance
    stt.feed(b"\x00" * (16000 * 2 * 2))

    text = ""
    deadline = time.monotonic() + 15.0
    async for ev in stt.events():
        if ev.kind == "final":
            text = ev.text
            break
        if ev.kind == "error":
            raise RuntimeError(f"STT error: {ev.text}")
        if time.monotonic() > deadline:
            raise TimeoutError("STT did not finalize in 15s")
    await stt.close()
    return text


async def llm_reply(prompt: str) -> str:
    llm = LlmRunner(instructions="Answer in one short sentence.")
    llm.add_user_text(prompt)
    out = []
    async for d in llm.stream():
        if d.kind == "text":
            out.append(d.text)
    return "".join(out)


async def main() -> int:
    s = get_settings()
    print(f"region={s.azure_speech_region}  endpoint={s.azure_openai_endpoint}")
    print(f"deployment={s.azure_openai_deployment}  voice={s.default_voice}")

    t0 = time.monotonic()
    print("\n[1/4] TTS synth (en-US)...")
    pcm = await synth_to_pcm("What is the capital of the United Arab Emirates?")
    print(f"   {len(pcm)} bytes, {time.monotonic() - t0:.2f}s")

    t1 = time.monotonic()
    print("[2/4] STT recognize (UAE North, Language ID en/ar)...")
    text = await stt_recognize(pcm)
    print(f"   transcript: {text!r}, {time.monotonic() - t1:.2f}s")

    t2 = time.monotonic()
    print("[3/4] gpt-4.1 streaming reply...")
    reply = await llm_reply(text or "What is the capital of the UAE?")
    print(f"   reply: {reply!r}, {time.monotonic() - t2:.2f}s")

    t3 = time.monotonic()
    print("[4/4] TTS synth reply...")
    out_pcm = await synth_to_pcm(reply)
    print(f"   {len(out_pcm)} bytes, {time.monotonic() - t3:.2f}s")

    print(f"\nTotal: {time.monotonic() - t0:.2f}s")
    return 0


if __name__ == "__main__":
    asyncio.run(main())
