"""Provider adapters for model calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .auth import PROVIDERS


@dataclass(frozen=True)
class ModelRequest:
    """Provider-neutral model request."""

    provider: str
    model: str
    api_base: str
    api_key: str
    system: str
    messages: list[dict[str, Any]]
    max_output_tokens: int = 2048


class ProviderAdapter(Protocol):
    """Interface implemented by provider-specific adapters."""

    api_mode: str

    def call(self, request: ModelRequest) -> str | dict[str, Any]:
        """Call the provider and return the raw model payload."""


class OfflineAdapter:
    """Offline fallback used when no API key is configured."""

    api_mode = "offline"

    def call(self, request: ModelRequest) -> str:
        user_text = ""
        for message in reversed(request.messages):
            if message.get("role") == "user":
                user_text = str(message.get("content", ""))
                break
        return (
            "_No API key configured. Run `rlm-ws auth` to set one up. "
            "Running in offline mode - I'll echo your input back._\n\n"
            f"> {user_text}"
        )


class OpenAIResponsesAdapter:
    """Adapter for OpenAI's Responses API."""

    api_mode = "responses"

    def call(self, request: ModelRequest) -> str | dict[str, Any]:
        try:
            response = httpx.post(
                f"{request.api_base.rstrip('/')}/responses",
                headers=_auth_headers(request.api_key),
                json={
                    "model": request.model,
                    "instructions": request.system,
                    "input": request.messages,
                    "max_output_tokens": request.max_output_tokens,
                    "store": False,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return _format_http_error(exc)
        except httpx.RequestError as exc:
            return _format_request_error(exc)
        except (KeyError, IndexError, TypeError) as exc:
            return _format_response_error(exc)


class ChatCompletionsAdapter:
    """Adapter for OpenAI-compatible chat-completions providers."""

    api_mode = "chat_completions"

    def call(self, request: ModelRequest) -> str:
        try:
            response = httpx.post(
                f"{request.api_base.rstrip('/')}/chat/completions",
                headers=_auth_headers(request.api_key),
                json={
                    "model": request.model,
                    "messages": [
                        {"role": "system", "content": request.system},
                        *request.messages,
                    ],
                    "max_tokens": request.max_output_tokens,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            return _format_http_error(exc)
        except httpx.RequestError as exc:
            return _format_request_error(exc)
        except (KeyError, IndexError, TypeError) as exc:
            return _format_response_error(exc)


def adapter_for(provider: str, api_base: str, api_key: str) -> ProviderAdapter:
    """Choose the adapter for a resolved provider config."""
    if not api_key:
        return OfflineAdapter()

    mode = PROVIDERS.get(provider, {}).get("api_mode")
    if mode == "responses" or provider == "openai" or "api.openai.com" in api_base:
        return OpenAIResponsesAdapter()
    return ChatCompletionsAdapter()


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _format_http_error(exc: httpx.HTTPStatusError) -> str:
    return f"_API error: {exc.response.status_code} {exc.response.text[:200]}_"


def _format_request_error(exc: httpx.RequestError) -> str:
    return f"_Request failed: {exc}_"


def _format_response_error(exc: Exception) -> str:
    return f"_Unexpected API response format: {exc}_"
