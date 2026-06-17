from __future__ import annotations

from pathlib import Path

from urisysedge.manifest import register_manifest_file
from urisysedge.runtime import Runtime


def test_register_manifest_file(tmp_path: Path):
    manifest = tmp_path / "demo.yaml"
    manifest.write_text(
        """
id: demo
version: 1
scheme: demo
uri_patterns:
  - pattern: demo://local/query/echo
    kind: query
    operation: echo
handlers:
  python:
    echo: python://urisysedge.runtime:Runtime
""".strip(),
        encoding="utf-8",
    )
    rt = Runtime()
    register_manifest_file(rt, manifest)
    assert len(rt.routes) == 1
    assert rt.routes[0].pattern == "demo://local/query/echo"
    assert rt.routes[0].operation == "echo"
