// Mic capture @ 16 kHz PCM16 → WS; binary frames back at 24 kHz → AudioBufferSource.

const $ = (id) => document.getElementById(id);
const log = (msg) => {
  $("events").textContent += msg + "\n";
  $("events").scrollTop = 1e9;
};
const setStatus = (text, cls) => {
  const el = $("status");
  el.textContent = text;
  el.className = "pill " + (cls || "");
};

let ws = null,
  audioCtx = null,
  micStream = null,
  processor = null,
  source = null;
let playbackTime = 0;

async function fetchToken(server, key) {
  const r = await fetch(server + "/v1/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": key },
    body: "{}",
  });
  if (!r.ok) throw new Error("auth failed: " + r.status);
  return r.json();
}

function downsampleTo16k(input, srcRate) {
  if (srcRate === 16000) return input;
  const ratio = srcRate / 16000;
  const outLen = Math.floor(input.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) out[i] = input[Math.floor(i * ratio)];
  return out;
}

function floatToPcm16(f32) {
  const out = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++) {
    const s = Math.max(-1, Math.min(1, f32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

async function start() {
  const server = $("server").value.trim();
  const apiKey = $("apiKey").value.trim();
  $("start").disabled = true;

  const sess = await fetchToken(server, apiKey);
  const wsUrl =
    server.replace(/^http/, "ws") +
    sess.ws_url +
    "?token=" +
    encodeURIComponent(sess.token);
  ws = new WebSocket(wsUrl);
  ws.binaryType = "arraybuffer";

  audioCtx = new AudioContext({ sampleRate: 24000 }); // playback rate
  playbackTime = audioCtx.currentTime;

  ws.onopen = async () => {
    setStatus("connected", "live");
    log("[open]");
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    // Use a separate context at native rate for capture, then resample.
    const captureCtx = new AudioContext();
    source = captureCtx.createMediaStreamSource(micStream);
    processor = captureCtx.createScriptProcessor(4096, 1, 1);
    source.connect(processor);
    processor.connect(captureCtx.destination);
    processor.onaudioprocess = (e) => {
      if (!ws || ws.readyState !== 1) return;
      const f32 = e.inputBuffer.getChannelData(0);
      const ds = downsampleTo16k(f32, captureCtx.sampleRate);
      ws.send(floatToPcm16(ds).buffer);
    };
    $("stop").disabled = false;
  };

  ws.onmessage = (m) => {
    if (typeof m.data === "string") {
      const ev = JSON.parse(m.data);
      handleEvent(ev);
    } else {
      // first 4 bytes = stream id
      const buf = new Uint8Array(m.data);
      const pcm = new Int16Array(m.data.slice(4));
      schedulePcm(pcm);
    }
  };
  ws.onclose = () => {
    setStatus("closed");
    $("start").disabled = false;
    $("stop").disabled = true;
  };
  ws.onerror = (e) => log("[error] " + e.message);
}

function handleEvent(ev) {
  log("← " + ev.type + (ev.text ? ": " + ev.text : ""));
  if (ev.type === "transcript.delta") $("transcript").textContent += ev.text;
  if (ev.type === "transcript.final") $("transcript").textContent += "\n— ";
  if (ev.type === "vad.speech_started") setStatus("user speaking", "speak");
  if (ev.type === "vad.speech_stopped") setStatus("listening", "live");
  if (ev.type === "barge_in.detected") {
    log("[barge-in @ " + ev.spoken_chars + " chars]");
    flushPlayback();
  }
}

function schedulePcm(int16) {
  if (!audioCtx) return;
  const buf = audioCtx.createBuffer(1, int16.length, 24000);
  const ch = buf.getChannelData(0);
  for (let i = 0; i < int16.length; i++) ch[i] = int16[i] / 0x8000;
  const src = audioCtx.createBufferSource();
  src.buffer = buf;
  src.connect(audioCtx.destination);
  const t = Math.max(audioCtx.currentTime, playbackTime);
  src.start(t);
  playbackTime = t + buf.duration;
}

function flushPlayback() {
  // Re-create context to immediately drop scheduled buffers
  if (audioCtx) {
    audioCtx.close();
  }
  audioCtx = new AudioContext({ sampleRate: 24000 });
  playbackTime = audioCtx.currentTime;
}

function stop() {
  if (processor) processor.disconnect();
  if (source) source.disconnect();
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  if (ws) ws.close();
  if (audioCtx) audioCtx.close();
  $("stop").disabled = true;
  $("start").disabled = false;
}

$("start").addEventListener("click", () =>
  start().catch((e) => {
    log("[fail] " + e);
    $("start").disabled = false;
  }),
);
$("stop").addEventListener("click", stop);
