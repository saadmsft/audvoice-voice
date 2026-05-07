/**
 * AuDesign Voice — TypeScript / JavaScript client SDK.
 *
 * Works in browsers and Node 18+ (uses native WebSocket + fetch).
 *
 * @example
 *   const client = new AudVoiceClient({ baseUrl: "https://voice.example", apiKey: "…" });
 *   await client.connect();
 *   await client.updateSession({ voice: "ar-AE-FatimaNeural", languages: ["ar-AE", "en-US"] });
 *   client.on("transcript.final", (e) => console.log("user:", e.text));
 *   client.on("audio", ({ streamId, pcm }) => playPcm(pcm)); // PCM16 24 kHz
 *   await client.sendAudio(pcm16k);   // PCM16 16 kHz from your mic
 */

export interface SessionConfig {
  instructions?: string;
  languages?: string[];
  voice?: string;
  model?: string;
  tools?: unknown[];
  turn_detection?: { type: "server_vad"; silence_ms?: number };
  rag?: { index_name: string; top_k?: number; semantic_config?: string };
  temperature?: number;
}

export interface ServerEvent {
  type: string;
  [k: string]: unknown;
}

export interface AudioFrame {
  streamId: number;
  pcm: Int16Array; // mono PCM16, 24 kHz
}

export interface ClientOptions {
  baseUrl: string;     // e.g. "https://voice.example.com"
  apiKey: string;
  fetchImpl?: typeof fetch;
  WebSocketImpl?: typeof WebSocket;
}

type Handler<T> = (payload: T) => void;

export class AudVoiceClient {
  private opts: ClientOptions;
  private ws: WebSocket | null = null;
  private sessionId = "";
  private handlers = new Map<string, Set<Handler<any>>>();

  constructor(opts: ClientOptions) {
    this.opts = opts;
  }

  /** Issue a WS token via /v1/sessions and connect to /v1/voice. */
  async connect(): Promise<void> {
    const f = this.opts.fetchImpl ?? fetch;
    const WS = this.opts.WebSocketImpl ?? WebSocket;
    const r = await f(`${this.opts.baseUrl}/v1/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": this.opts.apiKey },
      body: "{}",
    });
    if (!r.ok) throw new Error(`auth failed: ${r.status} ${await r.text()}`);
    const data = (await r.json()) as { session_id: string; token: string; ws_url: string };
    this.sessionId = data.session_id;

    const wsBase = this.opts.baseUrl.replace(/^http/, "ws");
    const url = `${wsBase}${data.ws_url}?token=${encodeURIComponent(data.token)}`;
    const ws = new WS(url) as WebSocket;
    ws.binaryType = "arraybuffer";
    this.ws = ws;

    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => resolve();
      ws.onerror = (e) => reject(e);
    });

    ws.onmessage = (m) => this.dispatch(m);
    ws.onclose = () => this.emit("close", { code: 1000 });
  }

  private dispatch(m: MessageEvent): void {
    if (typeof m.data === "string") {
      try {
        const ev = JSON.parse(m.data) as ServerEvent;
        this.emit(ev.type, ev);
        this.emit("*", ev);
      } catch {
        /* ignore */
      }
    } else {
      const buf = m.data as ArrayBuffer;
      if (buf.byteLength < 4) return;
      const view = new DataView(buf);
      const streamId = view.getUint32(0, false);
      const pcm = new Int16Array(buf.slice(4));
      this.emit("audio", { streamId, pcm } as AudioFrame);
    }
  }

  on<T = ServerEvent>(type: string, handler: Handler<T>): () => void {
    let set = this.handlers.get(type);
    if (!set) {
      set = new Set();
      this.handlers.set(type, set);
    }
    set.add(handler as Handler<any>);
    return () => set!.delete(handler as Handler<any>);
  }

  private emit(type: string, payload: unknown): void {
    this.handlers.get(type)?.forEach((h) => h(payload));
  }

  // ── send ──
  async updateSession(cfg: SessionConfig): Promise<void> {
    return this.sendEvent({ type: "session.update", session: cfg });
  }
  async sendEvent(event: Record<string, unknown>): Promise<void> {
    if (!this.ws) throw new Error("not connected");
    this.ws.send(JSON.stringify(event));
  }
  async sendAudio(pcm16Mono16k: ArrayBufferView | ArrayBuffer): Promise<void> {
    if (!this.ws) throw new Error("not connected");
    this.ws.send(pcm16Mono16k as ArrayBuffer);
  }
  async sendText(text: string): Promise<void> {
    return this.sendEvent({
      type: "conversation.item.create",
      item: { role: "user", content: text },
    });
  }
  async sendToolResult(callId: string, output: string): Promise<void> {
    return this.sendEvent({ type: "tool.result", call_id: callId, output });
  }
  async commitInput(): Promise<void> {
    return this.sendEvent({ type: "input_audio.commit" });
  }
  async cancelResponse(): Promise<void> {
    return this.sendEvent({ type: "response.cancel" });
  }
  close(): void {
    this.ws?.close();
    this.ws = null;
  }
  get sessionID(): string {
    return this.sessionId;
  }
}
