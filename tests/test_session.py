"""Session FSM tests with stubbed STT/LLM/TTS pipes (no Azure calls)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from audvoice import session as session_mod
from audvoice.llm import LlmDelta
from audvoice.protocol import SessionConfig
from audvoice.session import Session, State


class FakeStt:
    def __init__(self, *_, **__):
        self.q: asyncio.Queue = asyncio.Queue()
        self.fed: list[bytes] = []

    def feed(self, pcm: bytes) -> None:
        self.fed.append(pcm)

    async def events(self):
        while True:
            ev = await self.q.get()
            if ev is None:
                return
            yield ev

    async def close(self) -> None:
        await self.q.put(None)


class FakeTts:
    def __init__(self, *_, **__):
        self.cancelled = False
        self._spoken = 0

    async def feed_text(self, delta: str) -> AsyncIterator[bytes]:
        # 1 PCM byte per char so spoken_chars matches raw bytes for assertions
        self._spoken += len(delta)
        yield (b"\x00" * len(delta))

    async def flush(self) -> AsyncIterator[bytes]:
        if False:  # pragma: no cover
            yield b""

    def cancel(self) -> int:
        self.cancelled = True
        return self._spoken

    @property
    def spoken_chars(self) -> int:
        return self._spoken


class FakeLlm:
    def __init__(self) -> None:
        self.history: list[dict] = []
        self.instructions = ""
        self.model = None
        self.tools = None
        self.temperature = None
        self._next_text: list[str] = []

    def add_user_text(self, text: str) -> None:
        self.history.append({"role": "user", "content": text})

    def add_assistant_text(self, text, tool_calls=None) -> None:
        self.history.append({"role": "assistant", "content": text})

    def add_tool_result(self, *_args, **_kw) -> None:
        pass

    def truncate_assistant_at(self, n: int) -> None:
        if self.history and self.history[-1]["role"] == "assistant":
            self.history[-1]["content"] = (self.history[-1]["content"] or "")[:n]

    async def stream(self) -> AsyncIterator[LlmDelta]:
        for piece in self._next_text:
            yield LlmDelta(kind="text", text=piece)
        yield LlmDelta(kind="done", usage={"prompt_tokens": 1, "completion_tokens": 1})


@pytest.fixture(autouse=True)
def patch_pipes(monkeypatch):
    monkeypatch.setattr(session_mod, "SttPipe", FakeStt)
    monkeypatch.setattr(session_mod, "TtsPipe", FakeTts)
    yield


async def _collect(events_out: list, sess: Session) -> tuple:
    json_out: list[dict] = []
    bytes_out: list[tuple[int, bytes]] = []

    async def send_json(p):
        json_out.append(p)

    async def send_bytes(sid, b):
        bytes_out.append((sid, b))

    sess.send_json = send_json
    sess.send_bytes = send_bytes
    return json_out, bytes_out


@pytest.mark.asyncio
async def test_user_turn_triggers_response():
    sess = Session(session_id="s1", tenant_id="t1", send_json=None, send_bytes=None)
    fake_llm = FakeLlm()
    fake_llm._next_text = ["Hello there.", " How can I help?"]
    sess._llm = fake_llm

    json_out, bytes_out = await _collect([], sess)
    await sess.start()
    fake_stt: FakeStt = sess._stt  # type: ignore
    # simulate STT producing a final
    from audvoice.stt import SttEvent

    await fake_stt.q.put(SttEvent(kind="speech_started"))
    await fake_stt.q.put(SttEvent(kind="speech_stopped"))
    await fake_stt.q.put(SttEvent(kind="final", text="hi", language="en-US"))
    # let the response task run
    await asyncio.sleep(0.05)
    await sess.close()

    types = [e["type"] for e in json_out]
    assert "session.created" in types
    assert "vad.speech_started" in types
    assert "transcript.final" in types
    assert "response.text.delta" in types
    assert "response.done" in types
    # audio chunks went out
    assert any(b for _, b in bytes_out)


class HoldingLlm(FakeLlm):
    """Yields one chunk, then blocks on `release` so TTS stays in flight."""

    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def stream(self) -> AsyncIterator[LlmDelta]:
        yield LlmDelta(kind="text", text="A long answer mid-sentence.")
        await self.release.wait()


@pytest.mark.asyncio
async def test_barge_in_cancels_tts_and_truncates():
    sess = Session(session_id="s1", tenant_id="t1", send_json=None, send_bytes=None)
    fake_llm = HoldingLlm()
    sess._llm = fake_llm
    json_out, _ = await _collect([], sess)
    await sess.start()

    fake_stt: FakeStt = sess._stt  # type: ignore
    from audvoice.stt import SttEvent

    await fake_stt.q.put(SttEvent(kind="final", text="hi", language="en-US"))
    # Wait for AGENT_SPEAKING
    for _ in range(50):
        if sess.state == State.AGENT_SPEAKING:
            break
        await asyncio.sleep(0.01)
    assert sess.state == State.AGENT_SPEAKING

    # now simulate user speech during TTS
    await fake_stt.q.put(SttEvent(kind="speech_started"))
    await asyncio.sleep(0.05)

    types = [e["type"] for e in json_out]
    assert "barge_in.detected" in types
    assert sess._tts.cancelled  # type: ignore

    fake_llm.release.set()
    await sess.close()
