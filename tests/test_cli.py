"""Tests for the shared edge CLI builder (urisysedge.cli.build_edge_cli)."""

import json
import sys
import types

from urisysedge.cli import build_edge_cli
from urisysedge.runtime import Runtime


def _install_handler():
    mod = types.ModuleType("clitestpack")
    mod.echo = lambda payload, ctx: {"ok": True, "axis": ctx["params"].get("axis"), "said": payload.get("text")}
    sys.modules["clitestpack"] = mod


def _build_runtime(args):
    _install_handler()
    rt = Runtime(events_path=getattr(args, "events", None) or "/tmp/cli_test_events.jsonl")
    rt.register(
        "stepper://{device}/axis/{axis}/query/status",
        "python://clitestpack:echo",
        kind="query",
        operation="status",
    )
    return rt


def _add_args(parser):
    parser.add_argument("--events", default=None)


cli = build_edge_cli(
    "test-edge", _build_runtime, service="teststepper", default_port=8790,
    add_arguments=_add_args, allow_real=True,
)


def test_routes_command(capsys):
    rc = cli(["routes"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["ok"] is True
    assert out["routes"][0]["pattern"] == "stepper://{device}/axis/{axis}/query/status"
    assert out["routes"][0]["operation"] == "status"


def test_explain_command(capsys):
    rc = cli(["explain", "stepper://m1/axis/x/query/status"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["operation"] == "status"
    assert out["params"] == {"device": "m1", "axis": "x"}


def test_call_command(capsys):
    rc = cli(["call", "stepper://m1/axis/x/query/status", "--payload", '{"text": "hi"}'])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["ok"] is True
    assert out["result"] == {"ok": True, "axis": "x", "said": "hi"}


def test_call_unknown_uri_nonzero(capsys):
    rc = cli(["call", "stepper://m1/axis/x/command/nope"])
    capsys.readouterr()
    assert rc == 1


def test_allow_real_flag_in_context(capsys):
    # --allow-real is wired only when allow_real=True; it lands in handler context.
    recorded = {}

    def _bp(args):
        import sys as _s, types as _t
        m = _t.ModuleType("clitestpack2")
        def _h(payload, ctx):
            recorded["allow_real"] = ctx.get("allow_real")
            return {"ok": True}
        m.h = _h
        _s.modules["clitestpack2"] = m
        rt = Runtime(events_path="/tmp/cli_test2.jsonl")
        rt.register("x://{a}/query/y", "python://clitestpack2:h", kind="query", operation="y")
        return rt

    c = build_edge_cli("t2", _bp, service="t2", allow_real=True)
    c(["call", "x://1/query/y", "--allow-real"])
    capsys.readouterr()
    assert recorded["allow_real"] is True
