"""Unit tests for protocol parsing and the TTS sentence splitter."""

from audvoice.protocol import SessionConfig, SessionUpdate, ToolResult
from audvoice.tts import TtsPipe


def test_session_update_round_trip():
    raw = {
        "type": "session.update",
        "session": {
            "instructions": "be brief",
            "languages": ["ar-AE", "en-US"],
            "voice": "ar-AE-FatimaNeural",
            "turn_detection": {"type": "server_vad", "silence_ms": 400},
        },
    }
    ev = SessionUpdate.model_validate(raw)
    assert ev.session.voice == "ar-AE-FatimaNeural"
    assert ev.session.turn_detection.silence_ms == 400


def test_tool_result_validation():
    ev = ToolResult.model_validate(
        {"type": "tool.result", "call_id": "c1", "output": "{}"}
    )
    assert ev.call_id == "c1"


def test_sentence_terminator_finder():
    assert TtsPipe._first_terminator("hello world") == -1
    assert TtsPipe._first_terminator("hello. world") == 5
    # Arabic question mark first
    s = "ما هذا؟ what."
    assert TtsPipe._first_terminator(s) == s.index("؟")


def test_session_config_defaults():
    c = SessionConfig()
    assert c.voice is None
    assert c.languages is None
