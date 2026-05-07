"""Arabic-path live smoke."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "apps" / "orchestrator"))

from dotenv import load_dotenv

load_dotenv(ROOT / "apps" / "orchestrator" / ".env")

from live_smoke import llm_reply, stt_recognize, synth_to_pcm  # noqa: E402


async def main():
    print("Arabic path:")
    pcm = await synth_to_pcm(
        "ما هي عاصمة الإمارات العربية المتحدة؟", voice="ar-AE-FatimaNeural"
    )
    print(f"  TTS ar-AE: {len(pcm)} bytes")
    text = await stt_recognize(pcm)
    print(f"  STT: {text!r}")
    reply = await llm_reply(text)
    print(f"  LLM: {reply!r}")


if __name__ == "__main__":
    asyncio.run(main())
