# Orchestrator service

FastAPI app that exposes:

- `GET /healthz`
- `POST /v1/sessions` (header `X-API-Key`) → `{ session_id, token, ws_url, expires_in }`
- `WS /v1/voice?token=<jwt>` (or `Authorization: Bearer <jwt>`)

WS protocol: see [../../docs/protocol.md](../../docs/protocol.md).

## Run locally

```bash
cp .env.example .env       # fill in Azure keys
pip install -e .[dev,rag]
uvicorn audvoice.main:app --reload --port 8080
```

Smoke test:

```bash
curl -X POST http://localhost:8080/v1/sessions -H "X-API-Key: devkey"
```

Set `AUDVOICE_API_KEYS=devkey:tenant-dev` in `.env` for local dev.

## Internal layout

| Module        | Role                                                                                     |
| ------------- | ---------------------------------------------------------------------------------------- |
| `main.py`     | FastAPI app, WS handler, REST `/v1/sessions`                                             |
| `session.py`  | Per-connection state machine (LISTEN→USER_SPEAKING→THINKING→AGENT_SPEAKING) and barge-in |
| `stt.py`      | Azure Speech continuous recognition with Language ID                                     |
| `llm.py`      | Azure OpenAI streaming chat with tool-call assembly                                      |
| `tts.py`      | Sentence-incremental Azure TTS, cancellable for barge-in                                 |
| `rag.py`      | Optional Azure AI Search retrieval                                                       |
| `auth.py`     | Short-lived JWT issuance + verification                                                  |
| `settings.py` | Env-driven config                                                                        |
| `protocol.py` | Pydantic event models                                                                    |
