"""Optional VoiceRAG: hybrid + semantic search against Azure AI Search."""

from __future__ import annotations

import logging
from typing import Any

from .settings import get_settings

log = logging.getLogger(__name__)


async def retrieve(
    query: str, index_name: str, top_k: int = 5, semantic_config: str | None = None
) -> list[dict[str, Any]]:
    """Return list of {"content": ..., "title": ..., "url": ...}."""
    s = get_settings()
    if not s.azure_search_endpoint or not s.azure_search_key:
        log.warning("RAG requested but Azure AI Search not configured")
        return []
    try:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents.aio import SearchClient
    except ImportError:
        log.warning("azure-search-documents not installed; install with [rag] extra")
        return []

    client = SearchClient(
        endpoint=s.azure_search_endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(s.azure_search_key),
    )
    kwargs: dict[str, Any] = {"search_text": query, "top": top_k}
    if semantic_config:
        kwargs["query_type"] = "semantic"
        kwargs["semantic_configuration_name"] = semantic_config
    results: list[dict[str, Any]] = []
    async with client:
        async for doc in await client.search(**kwargs):
            results.append(
                {
                    "content": doc.get("content") or doc.get("chunk") or "",
                    "title": doc.get("title", ""),
                    "url": doc.get("url", ""),
                }
            )
    return results


def format_for_prompt(passages: list[dict[str, Any]]) -> str:
    if not passages:
        return ""
    lines = ["\n\n[Retrieved context]"]
    for i, p in enumerate(passages, 1):
        lines.append(f"[{i}] {p.get('title', '')}\n{p.get('content', '')}")
    return "\n".join(lines)
