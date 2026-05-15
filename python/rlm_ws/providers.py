"""Provider adapters for model calls."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

import httpx

from .auth import PROVIDERS


def _empty_headers() -> dict[str, str]:
    return {}


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
    extra_headers: dict[str, str] = field(default_factory=_empty_headers)


class ProviderAdapter(Protocol):
    """Interface implemented by provider-specific adapters."""

    api_mode: str

    def call(self, request: ModelRequest) -> str | dict[str, Any]:
        """Call the provider and return the raw model payload."""
        ...


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
    """Adapter for OpenAI's Responses API.

    The Codex ChatGPT backend (``chatgpt.com/backend-api/codex``)
    requires ``stream=true`` and returns SSE; api.openai.com accepts
    unary requests. Both routes hit the same adapter, branching on
    the api_base.
    """

    api_mode = "responses"

    def call(self, request: ModelRequest) -> str | dict[str, Any]:
        if _is_chatgpt_codex_route(request):
            return self._call_streaming(request)
        return self._call_unary(request)

    def _call_unary(self, request: ModelRequest) -> str | dict[str, Any]:
        try:
            response = httpx.post(
                f"{request.api_base.rstrip('/')}/responses",
                headers=_auth_headers(request.api_key, request.extra_headers),
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

    def _call_streaming(self, request: ModelRequest) -> str | dict[str, Any]:
        headers = _auth_headers(request.api_key, request.extra_headers)
        headers["Accept"] = "text/event-stream"
        url = f"{request.api_base.rstrip('/')}/responses"
        # The Codex ChatGPT backend rejects `max_output_tokens` and demands
        # `stream: true`. Mirror the body shape that the Codex CLI sends.
        body: dict[str, Any] = {
            "model": request.model,
            "instructions": request.system,
            "input": request.messages,
            "store": False,
            "stream": True,
        }

        try:
            with httpx.stream(
                "POST", url, headers=headers, json=body, timeout=120.0,
            ) as response:
                if response.status_code >= 400:
                    text = response.read().decode("utf-8", errors="replace")
                    return f"_API error: {response.status_code} {text[:300]}_"
                return _consume_responses_stream(response)
        except httpx.HTTPStatusError as exc:
            return _format_http_error(exc)
        except httpx.RequestError as exc:
            return _format_request_error(exc)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return _format_response_error(exc)


def _is_chatgpt_codex_route(request: ModelRequest) -> bool:
    """True when the request targets the Codex ChatGPT backend."""
    if "chatgpt.com" in request.api_base:
        return True
    headers = request.extra_headers or {}
    return "chatgpt-account-id" in headers


def _consume_responses_stream(
    response: httpx.Response,
) -> str | dict[str, Any]:
    """Drain a Responses-API SSE stream and return the final response.

    The Responses API emits a sequence of ``event:``/``data:`` lines
    terminated by ``response.completed``, whose ``data`` payload
    contains the full response object. Other events (deltas, item
    additions) are useful for live streaming but unnecessary here.
    """
    final: dict[str, Any] | None = None
    text_buf: list[str] = []
    event = ""
    for raw_line in response.iter_lines():
        line = raw_line.rstrip("\r")
        if not line:
            event = ""
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            break
        try:
            raw_payload: Any = json.loads(data_str)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw_payload, dict):
            continue
        payload = cast(dict[str, Any], raw_payload)
        if event == "response.output_text.delta":
            delta: Any = payload.get("delta")
            if isinstance(delta, str):
                text_buf.append(delta)
        elif event in ("response.completed", "response.finalized"):
            resp: Any = payload.get("response")
            if isinstance(resp, dict):
                final = cast(dict[str, Any], resp)
        elif event == "response.failed":
            err: Any = payload.get("error")
            return f"_API error: {err or payload}_"

    if final is None:
        return "_API error: streaming response ended without `response.completed`_"

    # Codex's ChatGPT backend often closes with a `response.completed`
    # whose `response.output` is empty — the text only arrived through
    # `response.output_text.delta` events. Stitch the buffered deltas
    # into the response so the downstream extractor finds them.
    if text_buf and not isinstance(final.get("output_text"), str):
        final["output_text"] = "".join(text_buf)
    return final


class ChatCompletionsAdapter:
    """Adapter for OpenAI-compatible chat-completions providers."""

    api_mode = "chat_completions"

    def call(self, request: ModelRequest) -> str:
        try:
            response = httpx.post(
                f"{request.api_base.rstrip('/')}/chat/completions",
                headers=_auth_headers(request.api_key, request.extra_headers),
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


def _auth_headers(
    api_key: str,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


def _format_http_error(exc: httpx.HTTPStatusError) -> str:
    return f"_API error: {exc.response.status_code} {exc.response.text[:200]}_"


def _format_request_error(exc: httpx.RequestError) -> str:
    return f"_Request failed: {exc}_"


def _format_response_error(exc: Exception) -> str:
    return f"_Unexpected API response format: {exc}_"
