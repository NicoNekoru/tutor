"""API key and credential management for model providers.

Two storage forms:

* ``~/.config/rlm-ws/auth.toml`` — keys typed in by the user, scoped to
  rlm-ws. Format::

      [keys]
      openai = "sk-..."
      openrouter = "sk-or-..."

      [default]
      provider = "openai"

* ``~/.codex/auth.json`` (or ``$CODEX_HOME/auth.json``) — credentials
  produced by ``codex login``. When the ``codex`` provider is selected,
  rlm-ws reads this file at resolve time rather than storing a copy. It
  supports both API-key and ChatGPT OAuth logins.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore[assignment]


DEFAULT_PROVIDER = "openai"

CODEX_ORIGINATOR = "rlm-ws"
CODEX_CHATGPT_BASE = "https://chatgpt.com/backend-api/codex"
OPENAI_API_BASE = "https://api.openai.com/v1"


PROVIDERS: dict[str, dict[str, object]] = {
    "codex": {
        "name": "Codex (reuse `codex login`)",
        "api_base": OPENAI_API_BASE,
        "env_var": "",
        "key_prefix": "",
        "signup_url": "https://github.com/openai/codex",
        "api_mode": "responses",
        "models": ["gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.5"],
        "managed": True,
    },
    "openai": {
        "name": "OpenAI",
        "api_base": OPENAI_API_BASE,
        "env_var": "OPENAI_API_KEY",
        "key_prefix": "sk-",
        "signup_url": "https://platform.openai.com/api-keys",
        "api_mode": "responses",
        "models": ["gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.5"],
        "managed": False,
    },
    "openrouter": {
        "name": "OpenRouter",
        "api_base": "https://openrouter.ai/api/v1",
        "env_var": "OPENROUTER_API_KEY",
        "key_prefix": "sk-or-",
        "signup_url": "https://openrouter.ai/keys",
        "api_mode": "chat_completions",
        "models": [
            "openai/gpt-5.4-mini",
            "openai/gpt-5.4-nano",
            "openai/gpt-5.5",
        ],
        "managed": False,
    },
}


def _empty_headers() -> dict[str, str]:
    return {}


@dataclass(frozen=True)
class ResolvedAuth:
    """Outcome of resolving a provider to concrete credentials."""

    provider: str
    api_key: str
    api_base: str
    model: str
    extra_headers: dict[str, str] = field(default_factory=_empty_headers)
    source: str = ""  # "env" | "auth.toml" | "codex.api_key" | "codex.chatgpt" | ""

    def as_tuple(self) -> tuple[str, str, str, str]:
        return self.provider, self.api_key, self.api_base, self.model


def _auth_path() -> Path:
    """Path to the rlm-ws auth config file."""
    config_dir = (
        Path(
            os.environ.get(
                "XDG_CONFIG_HOME",
                Path.home() / ".config",
            )
        )
        / "rlm-ws"
    )
    return config_dir / "auth.toml"


def _codex_auth_path() -> Path:
    """Path to the Codex CLI auth file (respects ``CODEX_HOME``)."""
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    base = Path(codex_home) if codex_home else Path.home() / ".codex"
    return base / "auth.json"


def is_managed(provider: str) -> bool:
    """True if rlm-ws does not store its own copy of the credential."""
    return bool(PROVIDERS.get(provider, {}).get("managed", False))


def load_auth() -> dict[str, Any]:
    """Load auth.toml. Returns empty dict if not found."""
    path = _auth_path()
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def save_auth(data: dict[str, Any]) -> Path:
    """Save auth.toml. Returns the path written."""
    path = _auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if tomli_w is not None:
        with open(path, "wb") as f:
            tomli_w.dump(data, f)
    else:
        lines: list[str] = []
        lines.append("[keys]")
        for k, v in data.get("keys", {}).items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
        lines.append("[default]")
        lines.append(
            f'provider = "{data.get("default", {}).get("provider", DEFAULT_PROVIDER)}"'
        )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    path.chmod(0o600)
    return path


def load_codex_auth() -> dict[str, Any] | None:
    """Load ``~/.codex/auth.json`` if present and parseable."""
    path = _codex_auth_path()
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data: Any = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict):
        return cast(dict[str, Any], data)
    return None


def codex_status() -> dict[str, Any]:
    """Summarize what's stored in the Codex auth file.

    Shape::

        {
            "path": Path,
            "found": bool,
            "has_api_key": bool,
            "has_chatgpt": bool,
            "account_id": str | None,
            "last_refresh": str | None,
        }
    """
    path = _codex_auth_path()
    data = load_codex_auth()
    if data is None:
        return {
            "path": path,
            "found": False,
            "has_api_key": False,
            "has_chatgpt": False,
            "account_id": None,
            "last_refresh": None,
        }

    api_key = str(data.get("OPENAI_API_KEY") or "").strip()
    raw_tokens: Any = data.get("tokens") or {}
    tokens: dict[str, Any] = (
        cast(dict[str, Any], raw_tokens) if isinstance(raw_tokens, dict) else {}
    )
    access = str(tokens.get("access_token") or "").strip()
    account: Any = tokens.get("account_id")
    return {
        "path": path,
        "found": True,
        "has_api_key": bool(api_key),
        "has_chatgpt": bool(access),
        "account_id": account if isinstance(account, str) and account else None,
        "last_refresh": data.get("last_refresh"),
    }


def resolve_codex_config(model_override: str | None = None) -> ResolvedAuth:
    """Resolve credentials from the Codex auth file.

    Prefers a raw API key when present (most reliable). Falls back to
    the ChatGPT OAuth access_token, which routes to the Codex backend.
    Returns an empty ``ResolvedAuth`` if Codex is not logged in.
    """
    info = PROVIDERS["codex"]
    raw_models: Any = info["models"]
    models: list[str] = (
        cast(list[str], raw_models) if isinstance(raw_models, list) else []
    )
    default_model: str = model_override or (models[0] if models else "")

    data = load_codex_auth()
    if data is None:
        return ResolvedAuth(
            provider="codex",
            api_key="",
            api_base=OPENAI_API_BASE,
            model=default_model,
            source="",
        )

    api_key = str(data.get("OPENAI_API_KEY") or "").strip()
    if api_key:
        return ResolvedAuth(
            provider="codex",
            api_key=api_key,
            api_base=OPENAI_API_BASE,
            model=default_model,
            source="codex.api_key",
        )

    raw_tokens: Any = data.get("tokens") or {}
    tokens: dict[str, Any] = (
        cast(dict[str, Any], raw_tokens) if isinstance(raw_tokens, dict) else {}
    )
    access = str(tokens.get("access_token") or "").strip()
    account_id: Any = tokens.get("account_id")
    if access:
        headers: dict[str, str] = {
            "OpenAI-Beta": "responses=experimental",
            "originator": CODEX_ORIGINATOR,
        }
        if isinstance(account_id, str) and account_id:
            headers["chatgpt-account-id"] = account_id
        return ResolvedAuth(
            provider="codex",
            api_key=access,
            api_base=CODEX_CHATGPT_BASE,
            model=default_model,
            extra_headers=headers,
            source="codex.chatgpt",
        )

    return ResolvedAuth(
        provider="codex",
        api_key="",
        api_base=OPENAI_API_BASE,
        model=default_model,
        source="",
    )


def resolve_api_config(provider: str | None = None) -> ResolvedAuth:
    """Resolve a provider to concrete credentials.

    Order of precedence for keyed providers:
    1. Environment variable (e.g. ``OPENAI_API_KEY``)
    2. ``~/.config/rlm-ws/auth.toml``
    3. Empty (caller falls back to offline mode)

    The ``codex`` provider is managed: credentials are pulled live from
    ``~/.codex/auth.json``.
    """
    auth = load_auth()

    if provider is None:
        provider = auth.get("default", {}).get("provider", DEFAULT_PROVIDER)

    if provider not in PROVIDERS:
        provider = DEFAULT_PROVIDER

    if provider == "codex":
        return resolve_codex_config()

    info = PROVIDERS[provider]
    api_base = str(info["api_base"])
    raw_models: Any = info["models"]
    models: list[str] = (
        cast(list[str], raw_models) if isinstance(raw_models, list) else []
    )
    default_model: str = models[0] if models else ""
    env_var = str(info["env_var"])

    env_key = os.environ.get(env_var, "") if env_var else ""
    if env_key:
        return ResolvedAuth(
            provider=provider,
            api_key=env_key,
            api_base=api_base,
            model=default_model,
            source="env",
        )

    saved_key = auth.get("keys", {}).get(provider, "")
    if saved_key:
        return ResolvedAuth(
            provider=provider,
            api_key=saved_key,
            api_base=api_base,
            model=default_model,
            source="auth.toml",
        )

    return ResolvedAuth(
        provider=provider,
        api_key="",
        api_base=api_base,
        model=default_model,
        source="",
    )


def get_api_key(provider: str | None = None) -> tuple[str, str, str]:
    """Resolve an API key, API base, and default model.

    Backwards-compatible helper that drops the provider name and extra
    headers from the resolution result.
    """
    resolved = resolve_api_config(provider)
    return resolved.api_key, resolved.api_base, resolved.model


def set_api_key(provider: str, key: str) -> Path:
    """Save an API key for a provider. Returns the auth file path."""
    if is_managed(provider):
        raise ValueError(
            f"{provider!r} is a managed provider; credentials live outside auth.toml."
        )
    auth = load_auth()
    if "keys" not in auth:
        auth["keys"] = {}
    auth["keys"][provider] = key
    if "default" not in auth:
        auth["default"] = {"provider": provider}
    return save_auth(auth)


def set_default_provider(provider: str) -> None:
    """Set the default provider."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider!r}")
    auth = load_auth()
    if "default" not in auth:
        auth["default"] = {}
    auth["default"]["provider"] = provider
    save_auth(auth)
