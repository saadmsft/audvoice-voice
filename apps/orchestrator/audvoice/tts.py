"""Azure Speech TTS pipe — incremental synthesis with cancel-for-barge-in."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator

import azure.cognitiveservices.speech as speechsdk

from . import aad
from .settings import get_settings

log = logging.getLogger(__name__)


@dataclass
class TtsChunk:
    pcm: bytes
    spoken_chars: int  # cumulative chars from text frontier corresponding to this audio


class TtsPipe:
    """Synthesizes a stream of text deltas into PCM16 24 kHz audio.

    Strategy: buffer LLM text deltas; when a sentence boundary is reached,
    fire one synth call. If cancel() is invoked, the in-flight synthesis is
    interrupted at the next chunk boundary and the pipe enters terminal state.
    """

    SENTENCE_TERMINATORS = ".!?؟。…\n"

    def __init__(self, voice: str | None = None):
        s = get_settings()
        self._voice = voice or s.default_voice
        if s.azure_speech_key:
            self._cfg = speechsdk.SpeechConfig(
                subscription=s.azure_speech_key, region=s.azure_speech_region
            )
        else:
            self._cfg = speechsdk.SpeechConfig(
                auth_token=aad.speech_auth_token(s.azure_speech_resource_id),
                region=s.azure_speech_region,
            )
        self._cfg.speech_synthesis_voice_name = self._voice
        # 24 kHz raw PCM
        self._cfg.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm
        )
        self._cancel = asyncio.Event()
        self._buffer = ""
        self._spoken = 0  # chars actually spoken so far

    async def synth_sentence(self, sentence: str) -> AsyncIterator[bytes]:
        """Synthesize one sentence; yield PCM chunks. Stops early on cancel()."""
        if not sentence.strip() or self._cancel.is_set():
            return

        synth = speechsdk.SpeechSynthesizer(speech_config=self._cfg, audio_config=None)
        loop = asyncio.get_event_loop()
        # speak_text_async returns a future; we read PCM from result.audio_data after
        # it's done, then yield as one chunk. Per-sentence latency keeps this OK.
        future = synth.speak_text_async(sentence)
        try:
            result = await loop.run_in_executor(None, future.get)
        except Exception as exc:
            log.exception("TTS error: %s", exc)
            return
        if self._cancel.is_set():
            return
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            data = result.audio_data
            self._spoken += len(sentence)
            # Chunk into ~40 ms frames (1920 bytes @ 24 kHz mono 16-bit) for smooth streaming
            frame = 1920
            for i in range(0, len(data), frame):
                if self._cancel.is_set():
                    return
                yield data[i : i + frame]
        else:
            log.warning("TTS not completed: %s / %s", result.reason, result.cancellation_details)

    async def feed_text(self, delta: str) -> AsyncIterator[bytes]:
        """Accumulate LLM text; emit synthesized PCM at sentence boundaries."""
        self._buffer += delta
        while True:
            idx = self._first_terminator(self._buffer)
            if idx < 0:
                break
            sentence, self._buffer = self._buffer[: idx + 1], self._buffer[idx + 1 :]
            async for chunk in self.synth_sentence(sentence):
                yield chunk

    async def flush(self) -> AsyncIterator[bytes]:
        """Synthesize any remaining buffered text."""
        if self._buffer.strip():
            async for chunk in self.synth_sentence(self._buffer):
                yield chunk
        self._buffer = ""

    def cancel(self) -> int:
        self._cancel.set()
        return self._spoken

    @property
    def spoken_chars(self) -> int:
        return self._spoken

    @classmethod
    def _first_terminator(cls, s: str) -> int:
        best = -1
        for ch in cls.SENTENCE_TERMINATORS:
            i = s.find(ch)
            if i >= 0 and (best < 0 or i < best):
                best = i
        return best
