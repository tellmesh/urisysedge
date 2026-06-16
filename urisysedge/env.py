from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_SECRET_NAMES = frozenset(
    {
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "LLM_API_KEY",
        "SMTP_PASSWORD",
        "MARKPACT_TOKEN",
    }
)


def _urisys_root() -> Path:
    # packages/python/urisysedge/env.py -> urisys/
    return Path(__file__).resolve().parents[3]


def load_urisys_env() -> str | None:
    """Load urisys/.env without overriding existing environment variables."""
    candidates: list[Path] = []
    if os.environ.get("URISYS_ENV_FILE"):
        candidates.append(Path(os.environ["URISYS_ENV_FILE"]))
    candidates.append(_urisys_root() / ".env")

    for path in candidates:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
        return str(path)
    return None


def _env_policy_candidates() -> list[Path]:
    candidates: list[Path] = []
    if os.environ.get("URISYS_ENV_POLICY"):
        candidates.append(Path(os.environ["URISYS_ENV_POLICY"]))
    root = _urisys_root()
    candidates.extend(
        [
            root / "config" / "env-policy.yaml",
            root / "urienv-docker/docker/config/env-policy.yaml",
            Path("/opt/urirdp/config/env-policy.yaml"),
            Path("/etc/urisys/env-policy.yaml"),
        ]
    )
    return candidates


def load_env_policy() -> dict[str, Any]:
    for path in _env_policy_candidates():
        if not path.is_file():
            continue
        try:
            import yaml  # type: ignore
        except ImportError:
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    return {}


def _env_config(context: dict[str, Any] | None) -> dict[str, Any]:
    if not context:
        return {}
    cfg = context.get("env_config")
    if isinstance(cfg, dict) and cfg:
        return cfg
    device = context.get("device_config") or {}
    env = device.get("env") if isinstance(device, dict) else {}
    return env if isinstance(env, dict) else {}


def resolve_env_var(
    name: str,
    context: dict[str, Any] | None = None,
    *,
    secret: bool | None = None,
    default: str | None = None,
) -> str | None:
    """Resolve env var via env:// policy when available, else process environment."""
    name = name.upper()
    context = context or {}
    if secret is None:
        secret = name in _SECRET_NAMES

    env_cfg = _env_config(context) or load_env_policy()
    if env_cfg:
        try:
            from urienv.handlers import secret_value, var_value

            handler_context = {
                **context,
                "env_config": env_cfg,
                "variables": {"name": name},
                "allow_secret_read": True,
            }
            if secret:
                result = secret_value({}, handler_context)
            else:
                try:
                    result = var_value({}, handler_context)
                except PermissionError:
                    result = {}
            if isinstance(result, dict):
                value = result.get("value")
                if value is not None:
                    return str(value)
        except ImportError:
            pass
        except PermissionError:
            pass

    return os.environ.get(name, default)


def is_secret_env(name: str) -> bool:
    return name.upper() in _SECRET_NAMES
