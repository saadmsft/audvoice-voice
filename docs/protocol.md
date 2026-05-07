# AuDesign Voice — Wire Protocol (v1)

JSON-over-WebSocket with interleaved binary frames for raw audio. Event names
are inspired by the OpenAI Realtime API so existing clients port easily, but
this is **not** a drop-in replacement.

## Connection

1. Client `POST /v1/sessions` with API key, receives:
   ```json
   { "session_id": "...", "ws_url": "wss://.../v1/voice", "token": "<JWT, 5 min TTL>" }
   ```
2. Client opens WS to `ws_url` with header `Authorization: Bearer <token>`.
3. Server replies with `session.created`.

## Audio format

| Direction       | Format                                                                                                          |
| --------------- | --------------------------------------------------------------------------------------------------------------- |
| Client → Server | PCM16 LE, mono, **16 kHz**, sent as **binary WebSocket frames** (recommended) or base64 in `input_audio.append` |
| Server → Client | PCM16 LE, mono, **24 kHz**, sent as **binary frames** prefixed with a 4-byte stream-id header                   |

Future: Opus support (negotiated via `session.update.audio_codec`).

## Events — Client → Server

### `session.update`
Configure the session. May be sent any time; merged with current config.

```json
{
  "type": "session.update",
  "session": {
    "instructions": "You are a helpful assistant for Dubai municipality...",
    "languages": ["ar-AE", "ar-SA", "en-US", "en-GB"],
    "voice": "en-US-AvaMultilingualNeural",
    "model": "gpt-4.1",
    "tools": [ { "type": "function", "function": { ... OpenAI tool schema ... } } ],
    "turn_detection": { "type": "server_vad", "silence_ms": 600 },
    "rag": { "index_name": "kb-municipality", "top_k": 5 }
  }
}
```

### `input_audio.append`
Optional JSON wrapper if not using binary frames.
```json
{ "type": "input_audio.append", "audio": "<base64 PCM16>" }
```

### `input_audio.commit`
Force end-of-utterance (overrides VAD). Optional.

### `response.cancel`
Abort the current assistant response (also triggered automatically on barge-in).

### `tool.result`
```json
{ "type": "tool.result", "call_id": "call_abc", "output": "{...json...}" }
```

### `conversation.item.create`
Inject text into the conversation without going through STT.
```json
{ "type": "conversation.item.create", "item": { "role": "user", "content": "..." } }
```

## Events — Server → Client

### `session.created`
```json
{ "type": "session.created", "session_id": "...", "model": "gpt-4.1", "voice": "..." }
```

### `vad.speech_started` / `vad.speech_stopped`
Server-side voice activity flags.

### `transcript.delta`
Streaming partial recognition.
```json
{ "type": "transcript.delta", "text": "ابي اعرف ", "language": "ar-AE" }
```

### `transcript.final`
```json
{ "type": "transcript.final", "text": "ابي اعرف what's the weather اليوم",
  "languages": ["ar-AE", "en-US"], "duration_ms": 2840 }
```

### `response.text.delta`
Streaming assistant text (token deltas from the LLM).

### `response.audio.delta`
Synthesized audio chunk. Sent as **binary frame**; the JSON event acts as
metadata only when streaming via base64.
```json
{ "type": "response.audio.delta", "stream_id": 7, "bytes": 4800 }
```

### `response.audio.done`
End of one synthesized assistant turn.

### `response.done`
Logical end of the assistant turn (after audio + text both flushed).
```json
{ "type": "response.done", "stream_id": 7, "usage": { "prompt_tokens": ..., "completion_tokens": ... } }
```

### `tool.call`
Mirrors OpenAI tool-call streaming.
```json
{ "type": "tool.call", "call_id": "call_abc", "name": "get_weather",
  "arguments": "{ \"city\": \"Dubai\" }" }
```

### `barge_in.detected`
Server detected user speech during TTS playback. TTS stream is cancelled.
```json
{ "type": "barge_in.detected", "stream_id": 7, "spoken_chars": 42 }
```

### `transcript.analysis`
Optional, when PII redaction or sentiment is enabled.
```json
{ "type": "transcript.analysis", "pii": [{ "category": "PhoneNumber", "offset": 12, "length": 9 }],
  "sentiment": "neutral" }
```

### `error`
```json
{ "type": "error", "code": "stt_unavailable", "message": "..." }
```

## State machine (server)

```
        ┌─────────────┐  speech_started     ┌────────────────┐
        │  IDLE/LISTEN├────────────────────▶│ USER_SPEAKING  │
        └─────────────┘                     └───────┬────────┘
              ▲                                     │ speech_stopped
              │                                     ▼
              │                          ┌─────────────────────┐
              │   response.done          │  THINKING (LLM)     │
              │◀─────────────────────────┤                     │
              │                          └──────────┬──────────┘
              │                                     │ first audio chunk
              │                                     ▼
              │                          ┌─────────────────────┐
              │  vad.speech_started      │  AGENT_SPEAKING     │
              ├────────────────── BARGE-IN ─────┤  (TTS playing) │
              │                          └─────────────────────┘
              │                                     │ audio.done
              └─────────────────────────────────────┘
```

## Auth

JWT (HS256) with claims `sub` (tenant ID), `sid` (session ID), `exp`. Issued
by `/v1/sessions` after API-key validation. WS upgrade rejects with 4401 close
code on invalid/expired token.

## Limits (v1)

- Max session duration: 30 min (configurable per tenant)
- Max audio frame size: 32 KB
- Max concurrent sessions per tenant: configurable (default 5)
