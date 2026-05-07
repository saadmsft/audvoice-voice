"""Protocol event models. JSON-over-WebSocket; binary frames carry raw audio."""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field

# ─── Session config ─────────────────────────────────────────────────────────


class TurnDetection(BaseModel):
    type: Literal["server_vad"] = "server_vad"
    silence_ms: int = 600


class RagConfig(BaseModel):
    index_name: str
    top_k: int = 5
    semantic_config: str | None = None


class SessionConfig(BaseModel):
    instructions: str | None = None
    languages: list[str] | None = None
    voice: str | None = None
    model: str | None = None
    tools: list[dict[str, Any]] | None = None
    turn_detection: TurnDetection | None = None
    rag: RagConfig | None = None
    temperature: float | None = None


# ─── Client → Server events ────────────────────────────────────────────────


class SessionUpdate(BaseModel):
    type: Literal["session.update"]
    session: SessionConfig


class InputAudioAppend(BaseModel):
    type: Literal["input_audio.append"]
    audio: str  # base64 PCM16


class InputAudioCommit(BaseModel):
    type: Literal["input_audio.commit"]


class ResponseCancel(BaseModel):
    type: Literal["response.cancel"]


class ToolResult(BaseModel):
    type: Literal["tool.result"]
    call_id: str
    output: str


class ConversationItem(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ConversationItemCreate(BaseModel):
    type: Literal["conversation.item.create"]
    item: ConversationItem


ClientEvent = Union[
    SessionUpdate,
    InputAudioAppend,
    InputAudioCommit,
    ResponseCancel,
    ToolResult,
    ConversationItemCreate,
]


# ─── Server → Client events ────────────────────────────────────────────────


class SessionCreated(BaseModel):
    type: Literal["session.created"] = "session.created"
    session_id: str
    model: str
    voice: str


class VadEvent(BaseModel):
    type: Literal["vad.speech_started", "vad.speech_stopped"]


class TranscriptDelta(BaseModel):
    type: Literal["transcript.delta"] = "transcript.delta"
    text: str
    language: str | None = None


class TranscriptFinal(BaseModel):
    type: Literal["transcript.final"] = "transcript.final"
    text: str
    languages: list[str] = Field(default_factory=list)
    duration_ms: int | None = None


class ResponseTextDelta(BaseModel):
    type: Literal["response.text.delta"] = "response.text.delta"
    stream_id: int
    delta: str


class ResponseAudioDelta(BaseModel):
    """Metadata event; the actual audio is sent as a binary frame immediately after."""

    type: Literal["response.audio.delta"] = "response.audio.delta"
    stream_id: int
    bytes: int


class ResponseAudioDone(BaseModel):
    type: Literal["response.audio.done"] = "response.audio.done"
    stream_id: int


class ResponseDone(BaseModel):
    type: Literal["response.done"] = "response.done"
    stream_id: int
    usage: dict[str, int] | None = None


class ToolCall(BaseModel):
    type: Literal["tool.call"] = "tool.call"
    call_id: str
    name: str
    arguments: str


class BargeInDetected(BaseModel):
    type: Literal["barge_in.detected"] = "barge_in.detected"
    stream_id: int
    spoken_chars: int = 0


class TranscriptAnalysis(BaseModel):
    type: Literal["transcript.analysis"] = "transcript.analysis"
    pii: list[dict[str, Any]] = Field(default_factory=list)
    sentiment: str | None = None


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
