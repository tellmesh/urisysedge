"""Characterization tests for the shared URI HTTP transport (urisysedge.http)."""

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from urisysedge.http import make_uri_handler


class _DictRuntime:
    """Edge-style runtime: call() returns a plain dict, routes have .pattern."""

    class _R:
        def __init__(self, pattern):
            self.pattern = pattern

    def __init__(self):
        self.routes = [self._R("llm://{host}/chat/query/completion")]
        self.events = self

    def call(self, uri, payload, context):
        if uri == "node://x/command/reboot":
            return {"ok": False, "uri": uri, "type": "policy_denied"}
        return {"ok": True, "uri": uri, "echo": payload}

    def tail(self, limit):
        return [{"event_type": "demo", "n": limit}]


class _ToDictRuntime:
    """uricore-style runtime: call() returns an object with to_dict()."""

    class _Result:
        def __init__(self, ok):
            self._ok = ok

        def to_dict(self):
            return {"ok": self._ok, "via": "to_dict"}

    routes = ()

    def call(self, uri, payload, context):
        return self._Result(ok=True)


def _serve(runtime, extensions=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_uri_handler(runtime, service="test", extensions=extensions))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
        return r.status, json.loads(r.read())


def _post(port, path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:  # 400 path
        return e.code, json.loads(e.read())


def test_health_routes_events():
    server, port = _serve(_DictRuntime())
    try:
        assert _get(port, "/health") == (200, {"ok": True, "service": "test", "runtime": "urisys-edge"})
        status, routes = _get(port, "/uri/routes")
        assert status == 200 and routes["routes"] == ["llm://{host}/chat/query/completion"]
        # /routes alias
        assert _get(port, "/routes")[1]["routes"] == routes["routes"]
        # /events with n=
        assert _get(port, "/events?n=7")[1]["events"] == [{"event_type": "demo", "n": 7}]
    finally:
        server.shutdown()


def test_uri_call_dict_and_status_mapping():
    server, port = _serve(_DictRuntime())
    try:
        assert _post(port, "/uri/call", {"uri": "llm://h/chat/query/completion", "payload": {"x": 1}}) == (
            200,
            {"ok": True, "uri": "llm://h/chat/query/completion", "echo": {"x": 1}},
        )
        # ok=False maps to HTTP 400
        status, body = _post(port, "/uri/call", {"uri": "node://x/command/reboot"})
        assert status == 400 and body["type"] == "policy_denied"
    finally:
        server.shutdown()


def test_uri_call_to_dict_runtime():
    server, port = _serve(_ToDictRuntime())
    try:
        assert _post(port, "/uri/call", {"uri": "x://y"}) == (200, {"ok": True, "via": "to_dict"})
    finally:
        server.shutdown()


def test_extension_endpoint():
    def install_pack(handler, runtime):
        handler._json(200, {"ok": True, "installed": True})

    server, port = _serve(_DictRuntime(), extensions={"POST /uri/pack": install_pack})
    try:
        assert _post(port, "/uri/pack", {"pack": "urillm"}) == (200, {"ok": True, "installed": True})
    finally:
        server.shutdown()


def test_cors_headers_and_options():
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_uri_handler(_DictRuntime(), service="test", cors=True))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as r:
            assert r.headers.get("Access-Control-Allow-Origin") == "*"
        # OPTIONS preflight answered with 204
        req = urllib.request.Request(f"http://127.0.0.1:{port}/uri/call", method="OPTIONS")
        with urllib.request.urlopen(req) as r:
            assert r.status == 204
    finally:
        server.shutdown()


def test_extension_overrides_builtin():
    """A server can override a built-in endpoint (e.g. richer /uri/routes)."""
    def rich_routes(handler, runtime):
        handler._json(200, {"ok": True, "routes": [{"pattern": "x://y", "kind": "query"}]})

    server, port = _serve(_DictRuntime(), extensions={"GET /uri/routes": rich_routes})
    try:
        status, body = _get(port, "/uri/routes")
        assert status == 200 and body["routes"] == [{"pattern": "x://y", "kind": "query"}]
    finally:
        server.shutdown()


def test_runtime_make_handler_still_works():
    """Backward-compat: urisysedge.runtime.make_handler/serve delegate to http."""
    from urisysedge.runtime import make_handler

    assert make_handler is not None
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(_DictRuntime()))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        # historical service label preserved
        assert _get(port, "/health")[1]["service"] == "urirdp"
    finally:
        server.shutdown()
