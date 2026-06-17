from __future__ import annotations

from typing import Any

import yaml


def register_manifest_file(runtime, manifest_path) -> None:
    with manifest_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    register_manifest_data(runtime, data, source=str(manifest_path))


def register_manifest_data(runtime, data: dict[str, Any], *, source: str = "") -> None:
    handlers = (data.get("handlers") or {}).get("python") or {}
    for item in data.get("uri_patterns") or []:
        operation = str(item["operation"])
        handler_ref = handlers.get(operation)
        if not handler_ref:
            label = source or data.get("id") or "manifest"
            raise KeyError(f"missing handler for operation {operation!r} in {label}")
        runtime.register(
            str(item["pattern"]),
            handler_ref,
            kind=str(item["kind"]),
            operation=operation,
            approval=str(
                item.get(
                    "approval",
                    "required" if item.get("kind") == "command" else "not_required",
                )
            ),
            side_effects=bool(item.get("side_effects", item.get("kind") == "command")),
        )


def register_manifest_files(runtime, manifest_paths) -> None:
    for manifest_path in manifest_paths:
        register_manifest_file(runtime, manifest_path)
