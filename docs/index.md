# AuDesign Voice — Documentation

A self-hosted, UAE-resident alternative to Azure's Voice Live API. Plug it into any LLM-based application via WebSocket or via the official SDKs.

![UAE North architecture](diagrams/azure-architecture.png){ width="780" }

## Read in order

1. **[Getting started](getting-started.md)** — install, run, and have a voice conversation in 5 minutes.
2. **[Wire protocol](protocol.md)** — every WebSocket event, audio format, and state transition.
3. **[LLM backends](llm-backends.md)** — wire the service to Azure OpenAI, OpenAI, or a Microsoft Foundry project.
4. **[Microsoft Agent Framework integration](integration-agent-framework.md)** — expose Agent Framework agents through AuDesign Voice.
5. **[SDKs](sdk.md)** — Python and TypeScript packages: install, publish, embed.
6. **[Deployment](deployment.md)** — Bicep + App Service for UAE North.
7. **[Operations & residency](operations.md)** — quotas, logs, the residency caveat.

## How a turn flows

![Conversation sequence](diagrams/conversation-sequence.png){ width="780" }

## Session state machine

![Session state machine](diagrams/session-state-machine.png){ width="780" }

## What you get

| Capability                              | Voice Live (Azure) | AuDesign Voice |
| --------------------------------------- | ------------------ | -------------- |
| UAE North data plane                    | ❌ not available   | ✅              |
| OpenAI-Realtime-style WS protocol       | ✅                  | ✅              |
| Barge-in, server VAD, end-of-turn       | ✅                  | ✅              |
| Tool / function calling passthrough     | ✅                  | ✅              |
| Arabic (`ar-AE`) + English code-switch  | ✅                  | ✅              |
| RAG over your knowledge base            | ✅ (VoiceRAG)       | ✅ (Azure AI Search) |
| Custom Neural Voice                     | ✅                  | ✅              |
| Bring your own LLM (OpenAI / Foundry)   | ❌                  | ✅              |
| Full source control                     | ❌                  | ✅              |
| Avatar (TTS Avatar)                     | ✅                  | ❌ (UAE region) |
| Native realtime audio model             | ✅                  | ❌ (UAE region) |

## SDKs

| Language               | Package                        | Install                             |
| ---------------------- | ------------------------------ | ----------------------------------- |
| Python (≥ 3.10) async  | `audvoice-client`              | `pip install audvoice-client`       |
| TypeScript / browser   | `@audvoice/client`             | `npm i @audvoice/client`            |
| Any other language     | Talk to the WebSocket directly | See [protocol](protocol.md)         |
