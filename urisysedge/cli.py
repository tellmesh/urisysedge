"""Shared edge CLI builder.

Every urisys edge package (uristepperedge, urikvmedge, uribrowseredge, urirdpedge,
...) exposes the same command surface over its runtime: call / explain / routes /
events / flow / serve. Historically each re-rolled the argparse plumbing and some
re-implemented ``flow`` (which already lives in ``urisysedge.runtime.run_flow``).

``build_edge_cli`` builds that CLI once. A package supplies only what is specific
to it:

* ``build_runtime(args)`` — construct its runtime from the parsed args,
* ``add_arguments(parser)`` — register its global args (``--config``, ``--packs``,
  ``--events`` with its own default, a UriBundle, ...),
* ``service`` / ``default_port`` / ``allow_real``.

So each edge ``cli.py`` collapses to a short declaration instead of re-rolling
argparse, flow and serve plumbing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from .http import serve as http_serve
from .runtime import Runtime, run_flow

RuntimeBuilder = Callable[[argparse.Namespace], Runtime]
ArgAdder = Callable[[argparse.ArgumentParser], None]


def _json_arg(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    if value.startswith("@"):
        return json.loads(Path(value[1:]).read_text(encoding="utf-8"))
    return json.loads(value)


def _emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_edge_cli(
    prog: str,
    build_runtime: RuntimeBuilder,
    *,
    service: str,
    default_port: int = 8790,
    default_host: str = "0.0.0.0",
    description: str | None = None,
    add_arguments: ArgAdder | None = None,
    allow_real: bool = False,
) -> Callable[[list[str] | None], int]:
    """Return a ``main(argv)`` argparse entry point for an edge package."""

    def _context(args: argparse.Namespace) -> dict[str, Any]:
        ctx = _json_arg(getattr(args, "context", None))
        if getattr(args, "approve", False):
            ctx["approved"] = True
        if getattr(args, "dry_run", False):
            ctx["dry_run"] = True
        if allow_real and getattr(args, "allow_real", False):
            ctx["allow_real"] = True
        return ctx

    def cmd_call(args: argparse.Namespace) -> int:
        rt = build_runtime(args)
        result = rt.call(args.uri, _json_arg(args.payload), _context(args))
        _emit(result)
        return 0 if result.get("ok") else 1

    def cmd_explain(args: argparse.Namespace) -> int:
        rt = build_runtime(args)
        route, params = rt.resolve(args.uri)
        _emit({
            "ok": True,
            "uri": args.uri,
            "operation": route.operation,
            "kind": route.kind,
            "params": params,
            "requires_approval": route.approval == "required",
            "side_effects": route.side_effects,
        })
        return 0

    def cmd_routes(args: argparse.Namespace) -> int:
        rt = build_runtime(args)
        _emit({"ok": True, "routes": [
            {
                "pattern": r.pattern,
                "operation": r.operation,
                "kind": r.kind,
                "requires_approval": r.approval == "required",
                "side_effects": r.side_effects,
            }
            for r in rt.routes
        ]})
        return 0

    def cmd_events(args: argparse.Namespace) -> int:
        rt = build_runtime(args)
        _emit({"ok": True, "events": rt.events.tail(args.limit)})
        return 0

    def cmd_flow(args: argparse.Namespace) -> int:
        rt = build_runtime(args)
        # Reuse the shared flow runner (YAML + JSON) instead of re-implementing it.
        results = run_flow(rt, args.path, _context(args))
        ok = all(r.get("ok") for r in results)
        _emit({"ok": ok, "results": results})
        return 0 if ok else 1

    def cmd_serve(args: argparse.Namespace) -> int:
        rt = build_runtime(args)
        http_serve(rt, args.host, args.port, service=service)
        return 0

    def _add_exec_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--approve", action="store_true")
        p.add_argument("--dry-run", action="store_true")
        if allow_real:
            p.add_argument("--allow-real", action="store_true")

    def main(argv: list[str] | None = None) -> int:
        parser = argparse.ArgumentParser(prog=prog, description=description or f"Edge runtime for {service}")
        if add_arguments is not None:
            add_arguments(parser)
        sub = parser.add_subparsers(dest="cmd", required=True)

        p = sub.add_parser("call")
        p.add_argument("uri")
        p.add_argument("--payload", default="{}")
        p.add_argument("--context", default="{}")
        _add_exec_flags(p)
        p.set_defaults(func=cmd_call)

        p = sub.add_parser("explain")
        p.add_argument("uri")
        p.set_defaults(func=cmd_explain)

        p = sub.add_parser("routes")
        p.set_defaults(func=cmd_routes)

        p = sub.add_parser("events")
        p.add_argument("--limit", type=int, default=20)
        p.set_defaults(func=cmd_events)

        p = sub.add_parser("flow")
        p.add_argument("path")
        _add_exec_flags(p)
        p.set_defaults(func=cmd_flow)

        p = sub.add_parser("serve")
        p.add_argument("--host", default=default_host)
        p.add_argument("--port", type=int, default=default_port)
        p.set_defaults(func=cmd_serve)

        args = parser.parse_args(argv)
        return args.func(args)

    return main
