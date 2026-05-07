from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Azure Speech
    azure_speech_key: str = ""
    azure_speech_region: str = "uaenorth"
    # Full ARM resource id (required when key is empty / Entra-only mode)
    azure_speech_resource_id: str = ""

    # LLM backend selection: "azure_openai" | "openai" | "foundry"
    llm_backend: Literal["azure_openai", "openai", "foundry"] = "azure_openai"

    # Azure OpenAI
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""  # leave empty for Entra/managed-identity auth
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment: str = "gpt-4.1"

    # OpenAI (or any OpenAI-compatible endpoint, e.g. vLLM, OpenRouter, Foundry serverless)
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # Microsoft Foundry project (when llm_backend == "foundry")
    foundry_project_endpoint: str = ""
    foundry_model: str = "gpt-4o"

    # Auth
    audvoice_jwt_secret: str = "dev-secret-change-me"
    audvoice_jwt_ttl_seconds: int = 300
    # Format: "key1:tenant1,key2:tenant2"
    audvoice_api_keys: str = ""

    # Optional services
    redis_url: str = ""
    azure_search_endpoint: str = ""
    azure_search_key: str = ""

    # Defaults applied unless overridden by session.update
    default_voice: str = "en-US-AvaMultilingualNeural"
    default_languages: str = "ar-AE,ar-SA,en-US,en-GB"
    default_model: str = "gpt-4.1"
    default_silence_ms: int = 600
    max_session_seconds: int = 1800

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @property
    def api_key_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for pair in self.audvoice_api_keys.split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            k, _, t = pair.partition(":")
            out[k.strip()] = t.strip()
        return out

    @property
    def language_list(self) -> list[str]:
        return [s.strip() for s in self.default_languages.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
