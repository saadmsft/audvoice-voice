# SDKs

Two first-party clients — Python (async) and TypeScript / browser. They wrap the [WebSocket protocol](protocol.md), handle auth, and demux the binary audio stream.

## Python — `audvoice-client`

```bash
pip install audvoice-client
pip install "audvoice-client[mic]"   # adds sounddevice + numpy for CLI demos
```

API surface:

| Method                                   | Purpose                                            |
| ---------------------------------------- | -------------------------------------------------- |
| `AudVoiceClient(base_url, api_key)`      | Construct                                          |
| `connect()` / `close()` / `async with`   | Lifecycle                                          |
| `update_session(**cfg)`                  | Set voice, languages, model, tools, instructions, RAG |
| `send_audio(pcm)`                        | PCM16 mono 16 kHz frames                           |
| `send_text(text)`                        | Inject user message (skip STT)                     |
| `commit_input()` / `cancel_response()`   | Forced end-of-turn / cancel current reply          |
| `send_tool_result(call_id, output)`      | Return a tool result                               |
| `events() -> AsyncIterator[dict]`        | All JSON events                                    |
| `audio() -> AsyncIterator[(sid, bytes)]` | Decoded binary audio chunks (PCM16 24 kHz)         |

See `packages/client_py/README.md` and `tests/live_ws.py` for full examples.

## TypeScript — `@audvoice/client`

```bash
npm install @audvoice/client
```

```ts
import { AudVoiceClient } from "@audvoice/client";

const client = new AudVoiceClient({ baseUrl: "https://voice.example", apiKey: "…" });
await client.connect();
await client.updateSession({ voice: "ar-AE-FatimaNeural", languages: ["ar-AE", "en-US"] });

client.on("transcript.final", (e) => console.log(e.text));
client.on("audio", ({ pcm }) => playPcm24k(pcm));   // Int16Array

await client.sendAudio(pcm16k);  // ArrayBuffer / Int16Array
```

Works in browsers and Node ≥ 18. For older Node, pass `fetchImpl` and `WebSocketImpl` (e.g. from `ws`).

## Other languages

The wire is plain JSON-over-WebSocket plus binary PCM frames; any language can talk to it. See [protocol.md](protocol.md). The minimum implementation is ~100 lines.

If you write one (Go, Rust, Swift, Kotlin, .NET), open a PR — we'll list it here.

## Publishing

### Python → PyPI

```bash
cd packages/client_py
pip install build twine
python -m build                                # produces dist/audvoice-client-*.whl
python -m twine upload dist/*                  # needs PYPI_API_TOKEN
```

### TypeScript → npm

```bash
cd packages/client_js
npm install
npm run build
npm publish --access public                    # needs NPM_TOKEN
```

### Versioning

Both packages follow SemVer. The wire protocol carries its own version under `session.created.protocol_version` (planned) — bump major when you change message shapes.

## Embedding the orchestrator

You can also embed the FastAPI app (`audvoice.main:app`) inside a larger service:

```python
from fastapi import FastAPI
from audvoice.main import app as voice_app

root = FastAPI()
root.mount("/voice", voice_app)         # now /voice/v1/sessions, /voice/v1/voice
```

Or import individual pieces (`Session`, `LlmRunner`, `SttPipe`, `TtsPipe`) if you want to write a different transport (Server-Sent Events, gRPC, ACS SIP, etc.).
