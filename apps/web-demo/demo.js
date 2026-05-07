// Mic capture @ 16 kHz PCM16 → WS; binary frames back at 24 kHz → AudioBufferSource.
// Half-duplex barge-in: while the agent is speaking we mute the mic unless a
// strong local energy spike is detected (real user voice). Right after a
// barge-in or end-of-utterance we suppress the mic for a short window to drop
// stale agent-tail audio that would otherwise get re-transcribed and cause the
// agent to "hear itself" and loop.

const $ = (id) => document.getElementById(id);

const stage = $("stage");
const caption = $("caption");
const brand = $("brand");
const eventsEl = $("events");

const log = (msg) => {
  eventsEl.textContent += msg + "\n";
  eventsEl.scrollTop = 1e9;
};

const setState = (s, label) => {
  stage.dataset.state = s;
  if (label !== undefined) caption.innerHTML = label;
};

let ws = null;
let playCtx = null;
let captureCtx = null;
let micStream = null;
let processor = null;
let source = null;
let playbackTime = 0;
let agentSpeaking = false;
let muteUntil = 0;          // perf time (ms) before which mic frames are dropped
let activeSources = [];     // scheduled buffer sources (for fast flush)

const TAIL_MUTE_MS = 250;     // suppress after barge-in / vad stop / agent done
const BARGE_RMS_GATE = 0.025; // local energy gate during agent speech
const BARGE_FRAMES   = 2;     // consecutive frames over gate to trigger barge-in
let bargeFrames = 0;

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

function rms(f32) {
  let sum = 0;
  for (let i = 0; i < f32.length; i++) sum += f32[i] * f32[i];
  return Math.sqrt(sum / f32.length);
}

async function start() {
  const server = $("server").value.trim();
  const apiKey = $("apiKey").value.trim();
  $("start").disabled = true;
  setState("idle", "Connecting…");

  let sess;
  try {
    sess = await fetchToken(server, apiKey);
  } catch (e) {
    setState("error", `<strong style="color:#ef4444">${e.message}</strong>`);
    brand.classList.add("error");
    $("start").disabled = false;
    return;
  }

  const wsUrl =
    server.replace(/^http/, "ws") +
    sess.ws_url +
    "?token=" +
    encodeURIComponent(sess.token);
  ws = new WebSocket(wsUrl);
  ws.binaryType = "arraybuffer";

  playCtx = new AudioContext({ sampleRate: 24000 });
  playbackTime = playCtx.currentTime;

  ws.onopen = async () => {
    brand.classList.add("connected");
    setState("listening", "Listening — go ahead");
    log("[open]");
    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (e) {
      setState("error", `<strong style="color:#ef4444">Mic blocked</strong>`);
      return;
    }
    captureCtx = new AudioContext();
    source = captureCtx.createMediaStreamSource(micStream);
    processor = captureCtx.createScriptProcessor(4096, 1, 1);
    source.connect(processor);
    processor.connect(captureCtx.destination);
    processor.onaudioprocess = (e) => {
      if (!ws || ws.readyState !== 1) return;
      const f32 = e.inputBuffer.getChannelData(0);

      const now = performance.now();
      // Drop stale audio briefly after barge-in / vad stop / agent finish.
      if (now < muteUntil) return;

      const energy = rms(f32);

      if (agentSpeaking) {
        // Half-duplex with local barge-in detection. Echo cancellation usually
        // suppresses the agent's own voice well enough that real user speech
        // dominates. Require a couple of consecutive frames over the gate so
        // a single click/pop doesn't trigger a cancel.
        if (energy < BARGE_RMS_GATE) {
          bargeFrames = 0;
          return; // suppress mic to prevent self-loop
        }
        bargeFrames++;
        if (bargeFrames < BARGE_FRAMES) return;
        // Real interrupt → kill playback locally, tell server to cancel.
        log("[local barge-in @ rms=" + energy.toFixed(3) + "]");
        agentSpeaking = false;
        bargeFrames = 0;
        flushPlayback();
        try {
          ws.send(JSON.stringify({ type: "response.cancel" }));
        } catch (_) {}
        setState("user", "Hearing you…");
        // Fall through and forward this frame so server's STT sees your voice.
      }

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
      const pcm = new Int16Array(m.data.slice(4));
      schedulePcm(pcm);
    }
  };
  ws.onclose = () => {
    brand.classList.remove("connected");
    setState("idle", "Disconnected");
    $("start").disabled = false;
    $("stop").disabled = true;
  };
  ws.onebargeFrames = 0;
        rror = () => log("[ws error]");
}

function handleEvent(ev) {
  log("← " + ev.type + (ev.text ? ": " + ev.text : ""));
  switch (ev.type) {
    case "session.created":
      setState("listening", "Listening — go ahead");
      break;
    case "vad.speech_started":
      setState("user", "Hearing you…");
      break;
    case "vad.speech_stopped":
      muteUntil = performance.now() + TAIL_MUTE_MS;
      if (!agentSpeaking) setState("listening", "Thinking…");
      break;
    case "response.audio.delta":
      if (!agentSpeaking) {
        agentSpeaking = true;
        setState("agent", "Speaking…");
      }
      break;
    case "response.audio.done":
    case "response.done":
      agentSpeaking = false;
      muteUntil = performance.now() + TAIL_MUTE_MS;
      setState("listening", "Listening — go ahead");
      break;
    case "barge_in.detected":
      log("[barge-in @ " + ev.spoken_chars + " chars]");
      flushPlayback();
      agentSpeaking = false;
      muteUntil = performance.now() + TAIL_MUTE_MS;
      setState("user", "Hearing you…");
      break;
    case "error":
      setState("error", `<strong style="color:#ef4444">${ev.message || ev.code}</strong>`);
      break;
  }
}

function schedulePcm(int16) {
  if (!playCtx) return;
  const buf = playCtx.createBuffer(1, int16.length, 24000);
  const ch = buf.getChannelData(0);
  for (let i = 0; i < int16.length; i++) ch[i] = int16[i] / 0x8000;
  const src = playCtx.createBufferSource();
  src.buffer = buf;
  src.connect(playCtx.destination);
  const t = Math.max(playCtx.currentTime, playbackTime);
  src.start(t);
  playbackTime = t + buf.duration;
  activeSources.push(src);
  src.onended = () => {
    activeSources = activeSources.filter((s) => s !== src);
  };
}

function flushPlayback() {
  // Stop all currently scheduled sources immediately (faster + no glitches
  // from re-creating the AudioContext mid-conversation).
  for (const s of activeSources) {
    try { s.stop(0); } catch (_) {}
  }
  activeSources = [];
  if (playCtx) playbackTime = playCtx.currentTime;
}

function stop() {
  agentSpeaking = false;
  flushPlayback();
  if (processor) processor.disconnect();
  if (source) source.disconnect();
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  if (ws) ws.close();
  if (captureCtx) captureCtx.close();
  if (playCtx) playCtx.close();
  $("stop").disabled = true;
  $("start").disabled = false;
  setState("idle", "Tap <strong>Start</strong> to begin");
}

$("start").addEventListener("click", () =>
  start().catch((e) => {
    log("[fail] " + e);
    setState("error", `<strong style="color:#ef4444">${e.message}</strong>`);
    $("start").disabled = false;
  }),
);
$("stop").addEventListener("click", stop);

// Settings drawer
$("gear").addEventListener("click", () => $("drawer").classList.add("open"));
$("drawerClose").addEventListener("click", () => $("drawer").classList.remove("open"));

// Debug events toggle
$("eventsToggle").addEventListener("click", () => eventsEl.classList.toggle("open"));
