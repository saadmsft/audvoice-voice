# @audvoice/client (TypeScript / JavaScript)

Browser + Node.js (≥18) client for the [AuDesign Voice](https://github.com/your-org/audvoice) WebSocket service.

```bash
npm install @audvoice/client
# or
pnpm add @audvoice/client
```

## Browser

```ts
import { AudVoiceClient } from "@audvoice/client";

const client = new AudVoiceClient({
  baseUrl: "https://voice.example.com",
  apiKey: import.meta.env.VITE_AUDVOICE_KEY,
});
await client.connect();

await client.updateSession({
  instructions: "You are a friendly Arabic/English voice agent.",
  voice: "ar-AE-FatimaNeural",
  languages: ["ar-AE", "en-US"],
});

client.on("transcript.final", (e) => console.log("USER:", e.text));
client.on("response.text.delta", (e) => process.stdout.write(e.delta));
client.on("audio", ({ streamId, pcm }) => playPcm24k(pcm)); // PCM16 mono 24 kHz

// Send PCM16 mono 16 kHz from getUserMedia (see web-demo for capture/resample)
await client.sendAudio(pcm16k);
```

## Tool calling

```ts
await client.updateSession({
  tools: [{
    type: "function",
    function: {
      name: "get_weather",
      description: "Current weather for a city",
      parameters: { type: "object", properties: { city: { type: "string" } }, required: ["city"] },
    },
  }],
});

client.on("tool.call", async ({ call_id, name, arguments: args }) => {
  const out = await myTool(name, JSON.parse(args));
  await client.sendToolResult(call_id, JSON.stringify(out));
});
```

## Events

All server → client JSON events (`transcript.delta`, `transcript.final`, `response.text.delta`, `response.audio.delta`, `response.audio.done`, `response.done`, `tool.call`, `barge_in.detected`, `vad.speech_started`, `vad.speech_stopped`, `error`) are dispatched by `client.on(type, handler)`. Binary audio frames are dispatched on the synthetic `"audio"` event with `{ streamId, pcm: Int16Array }`. Subscribe to `"*"` to see everything.

See the [protocol spec](https://github.com/your-org/audvoice/blob/main/docs/protocol.md) for the full event catalog.

## Node 18+

Works unchanged — `fetch` and `WebSocket` are global. For older Node, pass `fetchImpl` and `WebSocketImpl` (e.g. from `ws`) in the constructor.

## License

MIT
