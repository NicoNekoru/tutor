"""
API key management for model providers.

Keys are stored in ~/.config/rlm-ws/auth.toml (not in the workspace —
API keys should never be committed).

Format:
    [keys]
    openai = "sk-..."
    openrouter = "sk-or-..."

    [default]
    provider = "openai"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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


PROVIDERS = {
    "openai": {
        "name": "OpenAI",
        "api_base": "https://api.openai.com/v1",
        "env_var": "OPENAI_API_KEY",
        "key_prefix": "sk-",
        "signup_url": "https://platform.openai.com/api-keys",
        "api_mode": "responses",
        "models": ["gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.5"],
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
    },
}


def _auth_path() -> Path:
    """Path to the auth config file."""
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


def load_auth() -> dict:
    """Load auth.toml. Returns empty dict if not found."""
    path = _auth_path()
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def save_auth(data: dict) -> Path:
    """Save auth.toml. Returns the path written."""
    path = _auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if tomli_w is not None:
        with open(path, "wb") as f:
            tomli_w.dump(data, f)
    else:
        lines = []
        lines.append("[keys]")
        for k, v in data.get("keys", {}).items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
        lines.append("[default]")
        lines.append(
            f'provider = "{data.get("default", {}).get("provider", DEFAULT_PROVIDER)}"'
        )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Restrict permissions.
    path.chmod(0o600)
    return path


def resolve_api_config(provider: str | None = None) -> tuple[str, str, str, str]:
    """Resolve a provider and API key.

    Returns (provider, api_key, api_base, model) by checking:
    1. Environment variables (OPENAI_API_KEY, OPENROUTER_API_KEY, etc.)
    2. ~/.config/rlm-ws/auth.toml
    3. Returns empty strings if nothing found

    If provider is None, uses the default from auth.toml, falling back to OpenAI.
    """
    auth = load_auth()

    if provider is None:
        provider = auth.get("default", {}).get("provider", DEFAULT_PROVIDER)

    if provider not in PROVIDERS:
        provider = DEFAULT_PROVIDER

    provider_info = PROVIDERS[provider]

    # Check environment variable first.
    env_key = os.environ.get(provider_info["env_var"], "")
    if env_key:
        return provider, env_key, provider_info["api_base"], provider_info["models"][0]

    # Check auth.toml.
    saved_key = auth.get("keys", {}).get(provider, "")
    if saved_key:
        return provider, saved_key, provider_info["api_base"], provider_info["models"][0]

    return provider, "", provider_info["api_base"], provider_info["models"][0]


def get_api_key(provider: str | None = None) -> tuple[str, str, str]:
    """Resolve an API key, API base, and default model.

    Kept as the stable public helper for callers that do not need the resolved
    provider name.
    """
    _, api_key, api_base, model = resolve_api_config(provider)
    return api_key, api_base, model


def set_api_key(provider: str, key: str) -> Path:
    """Save an API key for a provider. Returns the auth file path."""
    auth = load_auth()
    if "keys" not in auth:
        auth["keys"] = {}
    auth["keys"][provider] = key
    if "default" not in auth:
        auth["default"] = {"provider": provider}
    return save_auth(auth)


def set_default_provider(provider: str) -> None:
    """Set the default provider."""
    auth = load_auth()
    if "default" not in auth:
        auth["default"] = {}
    auth["default"]["provider"] = provider
    save_auth(auth)
