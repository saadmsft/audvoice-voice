# audvoice-client (Python)

Async Python client for the [AuDesign Voice](https://github.com/your-org/audvoice) WebSocket service — a self-hosted, UAE-resident alternative to Azure's Voice Live API.

```bash
pip install audvoice-client
# optional mic / speaker helpers for CLI scripts
pip install "audvoice-client[mic]"
```

## Quick example

```python
import asyncio
from audvoice_client import AudVoiceClient

async def main():
    async with AudVoiceClient("https://voice.example.com", api_key="…") as c:
        await c.update_session(
            instructions="You are a friendly Arabic/English voice agent.",
            voice="ar-AE-FatimaNeural",
            languages=["ar-AE", "en-US"],
        )

        async def on_events():
            async for ev in c.events():
                if ev["type"] == "transcript.final":
                    print("USER:", ev["text"])
                elif ev["type"] == "response.text.delta":
                    print(ev["delta"], end="", flush=True)

        async def on_audio():
            # PCM16 mono 24 kHz — write to your audio device
            async for stream_id, pcm in c.audio():
                ...

        asyncio.gather(on_events(), on_audio())

        # Send PCM16 mono 16 kHz audio frames (e.g. 100 ms = 3200 bytes)
        while True:
            chunk = mic.read(3200)
            await c.send_audio(chunk)

asyncio.run(main())
```

## Inject text without going through STT

```python
await c.send_text("What's the weather in Dubai today?")
```

## Tool calling

```python
await c.update_session(
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }],
)

async for ev in c.events():
    if ev["type"] == "tool.call":
        result = call_my_function(ev["name"], ev["arguments"])
        await c.send_tool_result(ev["call_id"], result)
```

## Reference

| Method                              | Purpose                                |
| ----------------------------------- | -------------------------------------- |
| `connect()` / `close()`             | Lifecycle (also via `async with`)      |
| `update_session(**cfg)`             | Set voice, languages, model, tools, instructions, RAG |
| `send_audio(pcm)`                   | Push PCM16 mono 16 kHz frames          |
| `send_text(text)`                   | Inject a user message (no STT)         |
| `commit_input()`                    | Force end-of-utterance                 |
| `cancel_response()`                 | Stop current assistant turn            |
| `send_tool_result(call_id, output)` | Return a tool result to the model      |
| `events()`                          | Async iterator of JSON events          |
| `audio()`                           | Async iterator of `(stream_id, pcm)` chunks |

See the full [protocol spec](https://github.com/your-org/audvoice/blob/main/docs/protocol.md) for every event and field.

## License

MIT
