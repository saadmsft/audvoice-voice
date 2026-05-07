"""Azure Speech STT pipe with continuous Language ID for code-switching."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Callable

import azure.cognitiveservices.speech as speechsdk

from . import aad
from .settings import get_settings

log = logging.getLogger(__name__)


@dataclass
class SttEvent:
    kind: str  # "speech_started" | "speech_stopped" | "delta" | "final" | "error"
    text: str = ""
    language: str | None = None
    duration_ms: int | None = None


class SttPipe:
    """Wraps Azure Speech continuous recognition with a push audio stream.

    Audio in: PCM16 mono 16 kHz pushed via `feed(bytes)`.
    Events out: async iterator of `SttEvent`.
    """

    def __init__(self, languages: list[str] | None = None, silence_ms: int = 600):
        s = get_settings()
        self._loop = asyncio.get_event_loop()
        self._queue: asyncio.Queue[SttEvent] = asyncio.Queue()
        self._closed = False

        if s.azure_speech_key:
            speech_cfg = speechsdk.SpeechConfig(
                subscription=s.azure_speech_key, region=s.azure_speech_region
            )
        else:
            speech_cfg = speechsdk.SpeechConfig(
                auth_token=aad.speech_auth_token(s.azure_speech_resource_id),
                region=s.azure_speech_region,
            )
        speech_cfg.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous"
        )
        speech_cfg.set_property(
            speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, str(silence_ms)
        )
        # Profanity raw — let downstream apps decide.
        speech_cfg.set_profanity(speechsdk.ProfanityOption.Raw)

        langs = languages or s.language_list
        auto_lang = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(languages=langs)

        # 16 kHz / 16-bit / mono push stream
        fmt = speechsdk.audio.AudioStreamFormat(
            samples_per_second=16000, bits_per_sample=16, channels=1
        )
        self._push = speechsdk.audio.PushAudioInputStream(stream_format=fmt)
        audio_cfg = speechsdk.audio.AudioConfig(stream=self._push)

        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_cfg,
            auto_detect_source_language_config=auto_lang,
            audio_config=audio_cfg,
        )
        self._wire_callbacks()
        self._recognizer.start_continuous_recognition_async()

    # ── callbacks (run on SDK threads; marshal to asyncio) ──
    def _put(self, ev: SttEvent) -> None:
        if self._closed:
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, ev)

    def _wire_callbacks(self) -> None:
        def on_recognizing(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
            if evt.result.text:
                lang = self._detected_lang(evt.result)
                self._put(SttEvent(kind="delta", text=evt.result.text, language=lang))

        def on_recognized(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
            r = evt.result
            if r.reason == speechsdk.ResultReason.RecognizedSpeech and r.text:
                lang = self._detected_lang(r)
                # offset+duration are 100-ns ticks
                duration_ms = int(r.duration / 10_000) if r.duration else None
                self._put(
                    SttEvent(kind="final", text=r.text, language=lang, duration_ms=duration_ms)
                )

        def on_speech_start(_: speechsdk.SpeechRecognitionEventArgs) -> None:
            self._put(SttEvent(kind="speech_started"))

        def on_speech_end(_: speechsdk.SpeechRecognitionEventArgs) -> None:
            self._put(SttEvent(kind="speech_stopped"))

        def on_canceled(evt: speechsdk.SpeechRecognitionCanceledEventArgs) -> None:
            log.warning("STT canceled: %s / %s", evt.reason, evt.error_details)
            self._put(SttEvent(kind="error", text=str(evt.error_details or evt.reason)))

        self._recognizer.recognizing.connect(on_recognizing)
        self._recognizer.recognized.connect(on_recognized)
        self._recognizer.speech_start_detected.connect(on_speech_start)
        self._recognizer.speech_end_detected.connect(on_speech_end)
        self._recognizer.canceled.connect(on_canceled)

    @staticmethod
    def _detected_lang(result: speechsdk.SpeechRecognitionResult) -> str | None:
        try:
            auto = speechsdk.AutoDetectSourceLanguageResult(result)
            return auto.language or None
        except Exception:
            return None

    # ── public API ──
    def feed(self, pcm: bytes) -> None:
        if not self._closed and pcm:
            self._push.write(pcm)

    async def events(self) -> AsyncIterator[SttEvent]:
        while not self._closed:
            ev = await self._queue.get()
            yield ev

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._push.close()
            self._recognizer.stop_continuous_recognition_async().get()
        except Exception:
            log.exception("error stopping STT")
