# Operations & residency

## Data residency

| Pipeline stage | Where it runs                | Region-locked? |
| -------------- | ---------------------------- | -------------- |
| WebSocket / orchestrator | App Service in UAE North | ✅ yes |
| STT (Azure Speech) | AI Services in UAE North | ✅ yes — audio + transcripts stay regional |
| TTS (Azure Speech) | AI Services in UAE North | ✅ yes — text + audio stay regional |
| LLM (Azure OpenAI) | UAE North deployment | ⚠️ See below |
| LLM (Foundry / OpenAI) | Wherever you point it | ❌ Document in your privacy notice |
| Session state (Redis) | UAE North | ✅ yes |
| RAG index (Azure AI Search) | UAE North | ✅ yes |
| Logs (App Insights / Log Analytics) | UAE North | ✅ yes |

### The UAE OpenAI caveat

In UAE North, `gpt-4.1` is deployable as **GlobalStandard SKU only** — Microsoft routes inference globally for capacity, so request data may transit other Azure regions. Speech (STT/TTS) is unaffected and stays in UAE North.

Your options:

1. **Accept GlobalStandard** — fastest path, single region in your bill, but document the global routing in your privacy notice and DPA.
2. **Use a smaller regional Standard model** if/when one becomes available in UAE North.
3. **Move LLM to Sweden Central** for EU residency — split deployment, see [Deployment / region choice](deployment.md#region-choice).
4. **Bring your own model** via `LLM_BACKEND=openai` pointed at on-prem vLLM / Foundry Local.
5. **Sovereign deployment** via Core42 — separate engagement, not this repo.

## Auth

- **Client → orchestrator**: API key (`X-API-Key`) → JWT (HS256, 5 min TTL) → WebSocket auth header.
- **Orchestrator → Azure**: `DefaultAzureCredential` (Managed Identity in App Service, `az login` locally). Speech SDK uses `auth_token=aad#<resource_id>#<jwt>`; AOAI uses `azure_ad_token_provider`.

For production, replace the env-var API-key map with a Cosmos DB lookup (planned).

## Quotas to request before launch

Default UAE North limits will not survive production traffic. File quota requests for:

- **Azure OpenAI** TPM (tokens / minute) on your `gpt-4.1` deployment — minimum 100k for low single-digit concurrent users.
- **Azure Speech** continuous recognition concurrent sessions — minimum 50 for a small contact center.
- **App Service** outbound TCP connections per instance — Premium v3 default is 8000.

## Logs & telemetry

Every session emits to Application Insights:

| Event                  | Payload                                                |
| ---------------------- | ------------------------------------------------------ |
| `session.created`      | `tenant_id`, `session_id`, `voice`, `languages`        |
| `transcript.final`     | `text` (PII-redacted if enabled), `language`, `duration_ms` |
| `response.done`        | `tokens_in`, `tokens_out`, `latency_ms`                |
| `barge_in.detected`    | `spoken_chars`, `at_ms`                                |
| `tool.call`            | `name`, `latency_ms`                                   |
| `error`                | `code`, `message`                                      |
| `session.closed`       | `duration_ms`, `audio_in_bytes`, `audio_out_bytes`    |

Sample KQL:

```kql
// p95 first-audio latency over the last 24h
customEvents
| where name == "response.done"
| extend latency = todouble(customMeasurements["latency_ms"])
| summarize p50=percentile(latency, 50), p95=percentile(latency, 95), n=count() by bin(timestamp, 1h)
```

## Cost guidance

Per-minute voice cost (rough, based on 2026 retail prices):

| Component                              | $/minute (USD) |
| -------------------------------------- | -------------- |
| Azure Speech STT (standard real-time)  | ~$0.017        |
| Azure Speech TTS (Neural)              | ~$0.026        |
| Azure OpenAI gpt-4.1 (one short reply, ~200 tokens) | ~$0.005 |
| **Voice round-trip total**             | **~$0.05 / minute** |

Plus fixed:

- App Service P1v3: ~$160/mo
- Redis Basic C0: ~$16/mo
- Azure AI Search Basic: ~$75/mo (if RAG enabled)

## Limits today

| Setting                   | Default | Where to change                            |
| ------------------------- | ------- | ------------------------------------------ |
| Max session duration      | 30 min  | `MAX_SESSION_SECONDS` env var              |
| Max audio frame size      | 32 KB   | `--ws-max-size` uvicorn flag               |
| JWT TTL                   | 5 min   | `AUDVOICE_JWT_TTL_SECONDS` env var         |
| Sentence-boundary trigger | `.!?؟。…\n` | `apps/orchestrator/audvoice/tts.py:SENTENCE_TERMINATORS` |
| Default silence end-of-turn | 600 ms | `DEFAULT_SILENCE_MS` env var, per-session via `session.update.turn_detection.silence_ms` |

## Roadmap

- Cosmos DB tenant store (replaces env-var API-key map)
- Per-tenant rate limits (concurrent sessions, minutes/month)
- PII-redaction and sentiment via Azure AI Language
- Telephony channel via Azure Communication Services SIP
- Mobile SDKs (iOS / Android) wrapping the WS protocol
- Optional `disable_llm` mode for client-side Agent Framework integration
