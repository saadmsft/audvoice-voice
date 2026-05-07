"""Generate all marketing/architecture PNG diagrams for AuDesign Voice docs.

Run: source .venv/bin/activate && python docs/diagrams/generate.py
Outputs: docs/diagrams/*.png
"""

from __future__ import annotations

import subprocess
from pathlib import Path

OUT = Path(__file__).parent

# ── 1. Azure architecture ───────────────────────────────────────────────────
def azure_architecture() -> None:
    from diagrams import Cluster, Diagram, Edge
    from diagrams.azure.compute import AppServices, ContainerRegistries
    from diagrams.azure.database import CacheForRedis
    from diagrams.azure.devops import ApplicationInsights
    from diagrams.azure.identity import ManagedIdentities
    from diagrams.azure.ml import CognitiveServices
    from diagrams.azure.security import KeyVaults
    from diagrams.azure.web import Search
    from diagrams.onprem.client import User
    from diagrams.programming.framework import Fastapi

    with Diagram(
        "AuDesign Voice — UAE North architecture",
        filename=str(OUT / "azure-architecture"),
        outformat="png",
        show=False,
        direction="LR",
        graph_attr={"fontsize": "20", "bgcolor": "white", "splines": "spline", "pad": "0.5"},
    ):
        client = User("Browser / mobile / SDK")

        with Cluster("Azure subscription · UAE North", graph_attr={"bgcolor": "#f0f7ff"}):
            with Cluster("Compute"):
                acr = ContainerRegistries("ACR")
                app = AppServices("App Service\n(Linux P1v3, WS on)")
                appi = ApplicationInsights("App Insights")
                mi = ManagedIdentities("Managed\nIdentity")

            with Cluster("AI Services (S0)"):
                speech = CognitiveServices("Speech\n(STT + TTS,\nar-AE / en-US)")
                aoai = CognitiveServices("Azure OpenAI\n(gpt-4.1)")

            with Cluster("Data"):
                redis = CacheForRedis("Redis\n(sessions)")
                search = Search("AI Search\n(RAG)")
                kv = KeyVaults("Key Vault\n(JWT, API keys)")

        client >> Edge(label="WSS  PCM16 16k\n← PCM16 24k", color="#0066cc", style="bold") >> app
        app >> Edge(label="audio") >> speech
        app >> Edge(label="chat") >> aoai
        app >> Edge() >> redis
        app >> Edge(label="hybrid+semantic") >> search
        app >> Edge(style="dashed") >> kv
        mi >> Edge(style="dashed", label="Entra") >> aoai
        mi >> Edge(style="dashed", label="Entra") >> speech
        acr >> Edge(label="image") >> app
        app >> Edge(style="dotted", color="gray") >> appi


# ── 2. Conversation sequence ────────────────────────────────────────────────
SEQUENCE_DOT = r"""
digraph G {
  graph [bgcolor="white", rankdir=TB, fontname="Helvetica", fontsize=14, pad=0.4];
  node  [shape=box, style="filled,rounded", fontname="Helvetica", fontsize=12];
  edge  [fontname="Helvetica", fontsize=11];

  // Lifelines (rank=same forces the header row)
  subgraph cluster_header { style=invis;
    Browser    [label="Browser",                    fillcolor="#e3f2fd"];
    WS         [label="AuDesign WS",                 fillcolor="#bbdefb"];
    STT        [label="Azure Speech\nSTT",            fillcolor="#fff8e1"];
    LLM        [label="Azure OpenAI\nLLM",            fillcolor="#f3e5f5"];
    TTS        [label="Azure Speech\nTTS",            fillcolor="#fff8e1"];
    {rank=same; Browser; WS; STT; LLM; TTS;}
  }

  // Steps as labeled edges going down
  s1 [label="① mic PCM16 16k → frames",  shape=plain];
  s2 [label="② transcript.delta / .final",shape=plain, fillcolor="#c8e6c9"];
  s3 [label="③ chat completions stream",  shape=plain];
  s4 [label="④ response.text.delta",     shape=plain, fillcolor="#c8e6c9"];
  s5 [label="⑤ TTS sentence-incremental", shape=plain];
  s6 [label="⑥ response.audio.delta\n(PCM16 24k binary)", shape=plain, fillcolor="#c8e6c9"];
  s7 [label="⑦ Browser plays scheduled buffers", shape=plain];

  Browser -> WS  [label="① audio frames",        color="#1976d2", penwidth=2];
  WS      -> STT [label="push stream"];
  STT     -> WS  [label="② transcript", color="#2e7d32"];
  WS      -> LLM [label="③ user text"];
  LLM     -> WS  [label="④ token deltas",       color="#7b1fa2"];
  WS      -> TTS [label="⑤ sentence"];
  TTS     -> WS  [label="⑥ PCM chunks",         color="#f57c00"];
  WS      -> Browser [label="⑦ binary audio out", color="#1976d2", penwidth=2];

  // Barge-in subgraph
  subgraph cluster_barge {
    label="Barge-in (user speaks during TTS playback)";
    fontsize=13; color="#c62828"; style="rounded,dashed";
    bargein [label="vad.speech_started\n during AGENT_SPEAKING", fillcolor="#ffebee"];
    cancel  [label="↳ cancel TTS\n  truncate assistant message\n  emit barge_in.detected", fillcolor="#ffcdd2"];
    bargein -> cancel;
  }
}
"""


# ── 3. Session state machine ───────────────────────────────────────────────
STATE_MACHINE_DOT = r"""
digraph FSM {
  graph [bgcolor="white", rankdir=LR, fontname="Helvetica", fontsize=14, pad=0.4, nodesep=0.6];
  node  [shape=ellipse, style="filled,rounded", fontname="Helvetica", fontsize=13];
  edge  [fontname="Helvetica", fontsize=11];

  start  [shape=point, width=0.18, color=black];
  LISTEN          [label="LISTEN",          fillcolor="#e3f2fd"];
  USER_SPEAKING   [label="USER_SPEAKING",   fillcolor="#fff3cd"];
  THINKING        [label="THINKING\n(LLM streaming)", fillcolor="#e1bee7"];
  AGENT_SPEAKING  [label="AGENT_SPEAKING\n(TTS playing)", fillcolor="#ffe0b2"];
  CLOSED          [label="CLOSED", fillcolor="#cfd8dc"];

  start          -> LISTEN          [label="session.created"];
  LISTEN         -> USER_SPEAKING   [label="vad.speech_started"];
  USER_SPEAKING  -> THINKING        [label="vad.speech_stopped\nor transcript.final"];
  THINKING       -> AGENT_SPEAKING  [label="first audio chunk"];
  AGENT_SPEAKING -> LISTEN          [label="response.done"];

  // Barge-in: user starts talking during TTS
  AGENT_SPEAKING -> USER_SPEAKING   [label="BARGE-IN\ncancel TTS\ntruncate assistant", color="#c62828", fontcolor="#c62828", penwidth=2, constraint=false];

  // Anywhere → CLOSED
  LISTEN          -> CLOSED [color="gray", style="dashed", constraint=false];
  USER_SPEAKING   -> CLOSED [color="gray", style="dashed", constraint=false];
  THINKING        -> CLOSED [color="gray", style="dashed", constraint=false];
  AGENT_SPEAKING  -> CLOSED [color="gray", style="dashed", constraint=false];
}
"""


# ── 4. Pluggable LLM backends ──────────────────────────────────────────────
BACKENDS_DOT = r"""
digraph Backends {
  graph [bgcolor="white", rankdir=LR, fontname="Helvetica", fontsize=14, pad=0.4, nodesep=0.5];
  node  [shape=box, style="filled,rounded", fontname="Helvetica", fontsize=13];
  edge  [fontname="Helvetica", fontsize=11];

  subgraph cluster_core {
    label="AuDesign Voice orchestrator";
    fontsize=14; style="rounded,filled"; fillcolor="#f0f7ff"; color="#90caf9";
    SDK  [label="Python / TS\nSDK", fillcolor="#bbdefb"];
    WS   [label="WebSocket\n/v1/voice", fillcolor="#bbdefb"];
    LLM  [label="LlmRunner\n(streaming chat\n+ tool calls)", fillcolor="#90caf9"];
    SDK -> WS -> LLM;
  }

  // 3 backend boxes — selected by env var LLM_BACKEND
  AOAI    [label="azure_openai\n(default · UAE-resident)\nEntra or key", fillcolor="#c8e6c9"];
  OpenAI  [label="openai\n(OpenAI / vLLM /\nOpenRouter / Together)\nBearer key", fillcolor="#dcedc8"];
  Foundry [label="foundry\n(Microsoft Foundry\nproject route)\nEntra", fillcolor="#fff9c4"];

  LLM -> AOAI    [label="LLM_BACKEND=\nazure_openai", style="bold"];
  LLM -> OpenAI  [label="LLM_BACKEND=\nopenai"];
  LLM -> Foundry [label="LLM_BACKEND=\nfoundry"];

  note [shape=note, style=filled, fillcolor="#fffde7",
        label="Wire protocol unchanged.\nClients don't know which\nbackend is in use."];
  WS -> note [style=invis];
}
"""


# ── 5. Agent Framework patterns ────────────────────────────────────────────
AGENT_FRAMEWORK_DOT = r"""
digraph Patterns {
  graph [bgcolor="white", rankdir=TB, fontname="Helvetica", fontsize=14, pad=0.4, ranksep=0.6];
  node  [shape=box, style="filled,rounded", fontname="Helvetica", fontsize=12];
  edge  [fontname="Helvetica", fontsize=11];

  // ───── Pattern A — client-side agent ─────
  subgraph cluster_A {
    label="Pattern A — Client-side agent (recommended starting point)";
    fontsize=14; style="rounded,filled"; fillcolor="#e3f2fd"; color="#1976d2";

    A_user   [label="User\n(mic + speaker)", fillcolor="#bbdefb"];
    A_voice  [label="AuDesign Voice\n(WS, STT/TTS only,\nLLM hop unused)", fillcolor="#90caf9"];
    A_app    [label="Your Python app", fillcolor="#fff9c4"];
    A_agent  [label="Agent Framework\nChatAgent\n+ tools + threads", fillcolor="#c8e6c9"];
    A_llm    [label="LLM\n(AOAI / Foundry)", fillcolor="#fff8e1"];

    A_user  -> A_voice [label="audio in",  color="#1976d2", penwidth=2];
    A_voice -> A_app   [label="transcript.final", color="#2e7d32"];
    A_app   -> A_agent [label="run_stream(text)"];
    A_agent -> A_llm   [label="chat + tools"];
    A_llm   -> A_agent [label="reply"];
    A_agent -> A_app   [label="text"];
    A_app   -> A_voice [label="send_text(reply)"];
    A_voice -> A_user  [label="audio out", color="#1976d2", penwidth=2];
  }

  // ───── Pattern B — server-side agent ─────
  subgraph cluster_B {
    label="Pattern B — Server-side agent (production)";
    fontsize=14; style="rounded,filled"; fillcolor="#fff3e0"; color="#e65100";

    B_user   [label="User\n(thin client)", fillcolor="#ffe0b2"];
    B_voice  [label="AuDesign Voice\n+ AgentFrameworkRunner\n(replaces LlmRunner)", fillcolor="#ffcc80"];
    B_agent  [label="ChatAgent inside\norchestrator", fillcolor="#c8e6c9"];
    B_llm    [label="LLM + tools\n(AOAI / Foundry / MCP)", fillcolor="#fff8e1"];

    B_user  -> B_voice [label="audio + WS events", color="#e65100", penwidth=2];
    B_voice -> B_agent [label="user text"];
    B_agent -> B_llm   [label="chat + tools"];
    B_llm   -> B_agent;
    B_agent -> B_voice [label="reply text\n→ TTS"];
    B_voice -> B_user  [label="audio out", color="#e65100", penwidth=2];
  }
}
"""


def _render_dot(name: str, dot: str) -> None:
    src = OUT / f"{name}.dot"
    src.write_text(dot)
    subprocess.run(
        ["dot", "-Tpng", "-Gdpi=144", str(src), "-o", str(OUT / f"{name}.png")],
        check=True,
    )
    src.unlink()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("→ azure-architecture")
    azure_architecture()
    for name, dot in [
        ("conversation-sequence", SEQUENCE_DOT),
        ("session-state-machine", STATE_MACHINE_DOT),
        ("llm-backends", BACKENDS_DOT),
        ("agent-framework-patterns", AGENT_FRAMEWORK_DOT),
    ]:
        print(f"→ {name}")
        _render_dot(name, dot)
    print("✅ all diagrams in", OUT)


if __name__ == "__main__":
    main()
