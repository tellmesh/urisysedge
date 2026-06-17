"""Declarative pack composition for edge runtimes.

Historically each ``*edge`` package hand-wrote ``build_runtime`` with a hardcoded
``if "him" in packs: import urihim; urihim.register(rt)`` ladder. This module
replaces that with one reusable composer driven by:

* pack aliases  (``"kvm,him,ocr,llm"``)   -> import ``uri<alias>`` and call ``.register(rt)``
* manifest files (``manifest.yaml`` paths) -> ``register_manifest_file``
* a UriBundle Markpact                     -> derive packs from each imported contract's scheme

Every uri* pack follows the convention ``import uri<name>; uri<name>.register(rt)``,
so the alias->module rule defaults to that, with an ``alias_map`` for the few
exceptions (e.g. ``browser -> uribrowserdocker``).
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from .manifest import register_manifest_file
from .runtime import Runtime

# scheme/alias -> python module, only for names that are NOT simply ``uri<alias>``.
DEFAULT_ALIAS_MAP: dict[str, str] = {
    "browser": "uribrowserdocker",
}

_CONTRACT_SCHEME_RE = re.compile(r"^\s*scheme:\s*([A-Za-z0-9_.-]+)\s*$", re.MULTILINE)
_IMPORT_LINE_RE = re.compile(r"^\s*-\s*(.+?)\s*$", re.MULTILINE)


def resolve_pack_module(name: str, alias_map: dict[str, str] | None = None) -> str:
    """Map a pack alias/scheme to a python module name."""
    name = name.strip()
    merged = {**DEFAULT_ALIAS_MAP, **(alias_map or {})}
    if name in merged:
        return merged[name]
    return name if name.startswith("uri") else f"uri{name}"


def _split(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [p for p in (s.strip() for s in value.split(",")) if p]
    return [str(p).strip() for p in value if str(p).strip()]


def register_pack(rt: Runtime, name: str, *, alias_map: dict[str, str] | None = None) -> str:
    """Import the module for ``name`` and call its ``register(rt)``; returns module name."""
    module_name = resolve_pack_module(name, alias_map)
    module = importlib.import_module(module_name)
    register = getattr(module, "register", None)
    if not callable(register):
        raise AttributeError(f"pack {module_name!r} has no callable register(runtime)")
    register(rt)
    return module_name


def register_packs(rt: Runtime, packs: str | Iterable[str] | None, *, alias_map: dict[str, str] | None = None) -> list[str]:
    return [register_pack(rt, name, alias_map=alias_map) for name in _split(packs)]


def register_manifests(rt: Runtime, manifests: str | Iterable[str] | None) -> list[str]:
    loaded: list[str] = []
    for path in _split(manifests):
        register_manifest_file(rt, Path(path))
        loaded.append(path)
    return loaded


def bundle_packs(bundle_path: str | Path) -> list[str]:
    """Derive pack aliases (schemes) from a UriBundle Markpact's imported contracts.

    Reads the ``imports.contracts`` list, resolves each (relative to the bundle),
    and returns the ``scheme:`` declared in each contract block, de-duplicated in
    declaration order. Used so an edge can boot exactly the packs a bundle composes.
    """
    path = Path(bundle_path)
    text = path.read_text(encoding="utf-8")
    block = _bundle_block(text)
    contracts = _imports_contracts(block)
    schemes: list[str] = []
    for rel in contracts:
        contract_path = (path.parent / rel).resolve()
        if not contract_path.is_file():
            continue
        m = _CONTRACT_SCHEME_RE.search(contract_path.read_text(encoding="utf-8"))
        if m and m.group(1) not in schemes:
            schemes.append(m.group(1))
    return schemes


def _bundle_block(text: str) -> str:
    fence = re.search(r"```(?:yaml|yml)\s+markpact:bundle[^\n]*\n(.*?)^```", text, re.MULTILINE | re.DOTALL)
    return fence.group(1) if fence else text


def _imports_contracts(block: str) -> list[str]:
    """Extract the list items under ``imports:`` -> ``contracts:`` from a YAML block."""
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(block) or {}
        contracts = ((data.get("imports") or {}).get("contracts")) or []
        if isinstance(contracts, list):
            return [str(c).strip() for c in contracts if str(c).strip()]
    except Exception:
        pass
    return []


def build_runtime(
    *,
    packs: str | Iterable[str] | None = None,
    manifests: str | Iterable[str] | None = None,
    bundle: str | Path | None = None,
    config: dict[str, Any] | None = None,
    events_path: str | Path = "data/events.jsonl",
    alias_map: dict[str, str] | None = None,
    extra: Callable[[Runtime], None] | None = None,
) -> Runtime:
    """Build a Runtime and register packs from aliases, manifests and/or a bundle.

    ``packs`` and the schemes derived from ``bundle`` are merged (bundle first,
    preserving order, de-duplicated). ``extra`` is an optional callback for
    edge-specific registrations (e.g. a lab driver) that have no standalone pack.
    """
    rt = Runtime(events_path=events_path, config=config or {})

    names: list[str] = []
    if bundle is not None:
        names.extend(bundle_packs(bundle))
    for name in _split(packs):
        if name not in names:
            names.append(name)

    register_packs(rt, names, alias_map=alias_map)
    register_manifests(rt, manifests)
    if extra is not None:
        extra(rt)
    return rt


__all__ = [
    "DEFAULT_ALIAS_MAP",
    "resolve_pack_module",
    "register_pack",
    "register_packs",
    "register_manifests",
    "bundle_packs",
    "build_runtime",
]
