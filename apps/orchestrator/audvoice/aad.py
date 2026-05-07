"""Entra (AAD) auth helpers for Azure Speech and Azure OpenAI.

When `AZURE_OPENAI_API_KEY` / `AZURE_SPEECH_KEY` are empty, fall back to
`DefaultAzureCredential` (works locally via `az login`, in App Service via
managed identity, and in CI via workload identity).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from azure.identity import DefaultAzureCredential

log = logging.getLogger(__name__)

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"

_cred: DefaultAzureCredential | None = None
_lock = threading.Lock()


def _credential() -> DefaultAzureCredential:
    global _cred
    if _cred is None:
        with _lock:
            if _cred is None:
                _cred = DefaultAzureCredential(exclude_interactive_browser_credential=False)
    return _cred


def aoai_token_provider() -> Callable[[], str]:
    """Returns a no-arg callable that produces a valid Entra access token.

    The openai SDK calls this on every request; the credential caches tokens.
    """

    def _get() -> str:
        return _credential().get_token(COGNITIVE_SCOPE).token

    return _get


def speech_auth_token(resource_id: str) -> str:
    """Return Speech SDK auth-token string in `aad#<resource_id>#<jwt>` form."""
    if not resource_id:
        raise ValueError("AZURE_SPEECH_RESOURCE_ID must be set when using Entra auth")
    jwt = _credential().get_token(COGNITIVE_SCOPE).token
    return f"aad#{resource_id}#{jwt}"
