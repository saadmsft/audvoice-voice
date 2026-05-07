"""Streaming chat with tool-call passthrough.

Pluggable backend: Azure OpenAI (UAE-resident), OpenAI (or any OpenAI-compatible
endpoint such as Foundry serverless / vLLM / OpenRouter), or Microsoft Foundry
project endpoint via the AOAI-compatible `/openai/v1` route.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI

from . import aad
from .settings import get_settings

log = logging.getLogger(__name__)


@dataclass
class LlmDelta:
    kind: str  # "text" | "tool_call" | "done"
    text: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_args: str = ""
    usage: dict[str, int] | None = None


@dataclass
class LlmRunner:
    """Holds rolling conversation state for one session."""

    instructions: str = "You are a helpful voice assistant."
    model: str | None = None
    tools: list[dict[str, Any]] | None = None
    temperature: float | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    _client: AsyncAzureOpenAI | AsyncOpenAI | None = None
    _is_azure: bool = False

    def client(self) -> AsyncAzureOpenAI | AsyncOpenAI:
        if self._client is not None:
            return self._client
        s = get_settings()
        backend = s.llm_backend

        if backend == "azure_openai":
            kwargs: dict[str, Any] = {
                "api_version": s.azure_openai_api_version,
                "azure_endpoint": s.azure_openai_endpoint,
            }
            if s.azure_openai_api_key:
                kwargs["api_key"] = s.azure_openai_api_key
            else:
                kwargs["azure_ad_token_provider"] = aad.aoai_token_provider()
            self._client = AsyncAzureOpenAI(**kwargs)
            self._is_azure = True
        elif backend == "openai":
            self._client = AsyncOpenAI(
                api_key=s.openai_api_key, base_url=s.openai_base_url
            )
        elif backend == "foundry":
            # Foundry projects expose an OpenAI-compatible route at
            # {project_endpoint}/openai/v1 — Entra-authed.
            base_url = s.foundry_project_endpoint.rstrip("/") + "/openai/v1"
            token = aad.aoai_token_provider()
            # AsyncOpenAI doesn't natively call a token provider per request,
            # so we fetch one fresh; the credential caches and refreshes.
            self._client = AsyncOpenAI(api_key=token(), base_url=base_url)
        else:
            raise ValueError(f"unknown llm_backend: {backend}")
        return self._client

    def _resolve_model(self) -> str:
        s = get_settings()
        if self.model:
            return self.model
        if s.llm_backend == "azure_openai":
            return s.azure_openai_deployment
        if s.llm_backend == "openai":
            return s.openai_model
        if s.llm_backend == "foundry":
            return s.foundry_model
        return "gpt-4o-mini"

    def add_user_text(self, text: str) -> None:
        self.history.append({"role": "user", "content": text})

    def add_assistant_text(self, text: str, tool_calls: list[dict[str, Any]] | None = None) -> None:
        msg: dict[str, Any] = {"role": "assistant", "content": text or None}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.history.append(msg)

    def add_tool_result(self, call_id: str, output: str) -> None:
        self.history.append({"role": "tool", "tool_call_id": call_id, "content": output})

    def truncate_assistant_at(self, chars: int) -> None:
        """On barge-in, truncate the last assistant message to `chars` chars."""
        if not self.history:
            return
        last = self.history[-1]
        if last.get("role") == "assistant" and isinstance(last.get("content"), str):
            last["content"] = last["content"][:chars]

    async def stream(self) -> AsyncIterator[LlmDelta]:
        """Run one assistant turn, streaming deltas."""
        messages = [{"role": "system", "content": self.instructions}, *self.history]

        kwargs: dict[str, Any] = {
            "model": self._resolve_model(),
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self.tools:
            kwargs["tools"] = self.tools
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature

        # Tool-call assembly (deltas come piecemeal)
        tc_buffer: dict[int, dict[str, str]] = {}
        full_text: list[str] = []

        try:
            stream = await self.client().chat.completions.create(**kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    if chunk.usage:
                        yield LlmDelta(kind="done", usage=chunk.usage.model_dump())
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    full_text.append(delta.content)
                    yield LlmDelta(kind="text", text=delta.content)
                if delta and delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        slot = tc_buffer.setdefault(idx, {"id": "", "name": "", "args": ""})
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function and tc.function.name:
                            slot["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            slot["args"] += tc.function.arguments
        except Exception as exc:
            log.exception("LLM stream error")
            raise

        # Flush completed tool calls
        for slot in tc_buffer.values():
            if slot["id"]:
                yield LlmDelta(
                    kind="tool_call",
                    tool_call_id=slot["id"],
                    tool_name=slot["name"],
                    tool_args=slot["args"],
                )

        # Persist assistant turn
        tool_calls_payload = [
            {
                "id": s["id"],
                "type": "function",
                "function": {"name": s["name"], "arguments": s["args"]},
            }
            for s in tc_buffer.values()
            if s["id"]
        ] or None
        self.add_assistant_text("".join(full_text), tool_calls=tool_calls_payload)
