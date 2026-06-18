from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from urisysedge import compose
from urisysedge.runtime import Runtime


def test_resolve_pack_module_default_and_alias():
    assert compose.resolve_pack_module("him") == "urihim"
    assert compose.resolve_pack_module("uristepper") == "uristepper"  # already prefixed
    assert compose.resolve_pack_module("browser") == "uribrowserdocker"  # default exception
    assert compose.resolve_pack_module("tts") == "uristt"
    assert compose.resolve_pack_module("kvm", {"kvm": "urikvm_x"}) == "urikvm_x"


def _install_fake_pack(monkeypatch: pytest.MonkeyPatch, module_name: str, scheme: str) -> None:
    mod = types.ModuleType(module_name)

    def register(rt: Runtime) -> None:
        rt.register(f"{scheme}://local/query/ping", "python://x:y", kind="query", operation=f"{scheme}.ping")

    mod.register = register  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, mod)


def test_register_packs_imports_and_registers(monkeypatch):
    _install_fake_pack(monkeypatch, "urifoo", "foo")
    _install_fake_pack(monkeypatch, "uribar", "bar")
    rt = Runtime(events_path="/tmp/opencode/compose-test.jsonl")
    loaded = compose.register_packs(rt, "foo,bar")
    assert loaded == ["urifoo", "uribar"]
    assert {r.pattern.split("://")[0] for r in rt.routes} == {"foo", "bar"}


def test_build_runtime_merges_bundle_and_packs(monkeypatch, tmp_path: Path):
    _install_fake_pack(monkeypatch, "urialpha", "alpha")
    _install_fake_pack(monkeypatch, "uribeta", "beta")

    contract = tmp_path / "alpha.contract.markpact.md"
    contract.write_text(
        "```yaml markpact:contract\nkind: UriContract\nscheme: alpha\n"
        "queries:\n  - id: alpha.ping\n    pattern: alpha://local/query/ping\n```\n",
        encoding="utf-8",
    )
    bundle = tmp_path / "stack.bundle.markpact.md"
    bundle.write_text(
        "```yaml markpact:bundle\nkind: UriBundle\nimports:\n  contracts:\n"
        "    - ./alpha.contract.markpact.md\n```\n",
        encoding="utf-8",
    )

    assert compose.bundle_packs(bundle) == ["alpha"]

    rt = compose.build_runtime(packs="beta", bundle=bundle, events_path=str(tmp_path / "ev.jsonl"))
    assert {r.pattern.split("://")[0] for r in rt.routes} == {"alpha", "beta"}
