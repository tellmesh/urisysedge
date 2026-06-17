"""Shared URI HTTP transport — one implementation of the urisys HTTP contract.

Historically every node/agent re-implemented the same endpoints from scratch
(urisys-node, automation-lab, www api-bridge, urisys, urisysedge...). This is
the single shared implementation:

    GET  /health           -> {ok, service, runtime}
    GET  /uri/routes        -> {ok, routes: [pattern, ...]}   (alias: /routes)
    GET  /events[?n=N]      -> {ok, events: [...]}            (if runtime exposes events)
    POST /uri/call          -> {uri, payload, context} -> dispatch result

It is *duck-typed* on the runtime so it works with any of them without forcing a
dependency: the runtime only needs

    * ``call(uri, payload, context)`` returning a ``dict`` or an object with
      ``to_dict()`` (uricore ``DispatchResult``),
    * ``routes`` — an iterable whose items expose ``.pattern`` (or dicts/strings),
    * optionally ``events`` with ``tail(limit)``.

Runtime-specific endpoints (e.g. urisys-node's ``POST /uri/pack``) are injected
via ``extensions={"POST /uri/pack": handler}`` instead of forking the transport.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

ExtensionHandler = Callable[[BaseHTTPRequestHandler, Any], None]


def _as_dict(result: Any) -> dict[str, Any]:
    """Normalize a dispatch result to a JSON-serializable dict."""
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, dict):
        return result
    return {"ok": True, "result": result}


def _routes_list(runtime: Any) -> list[str]:
    patterns: list[str] = []
    for r in getattr(runtime, "routes", []) or []:
        pattern = getattr(r, "pattern", None)
        if pattern is None and isinstance(r, dict):
            pattern = r.get("pattern")
        patterns.append(pattern if pattern is not None else str(r))
    return patterns


def make_uri_handler(
    runtime: Any,
    *,
    service: str = "urisys",
    extensions: dict[str, ExtensionHandler] | None = None,
    cors: bool = False,
):
    """Build a ``BaseHTTPRequestHandler`` serving the URI contract for ``runtime``.

    ``cors=True`` emits permissive CORS headers and answers preflight
    ``OPTIONS`` — needed by browser clients (e.g. the www frontend) so those
    servers can drop their bespoke handlers instead of forking the transport.
    """

    ext = extensions or {}

    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, data: dict[str, Any]) -> None:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            if cors:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self) -> None:
            if cors:
                return self._json(204, {})
            return self._json(404, {"ok": False, "error": "not found"})

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            # Extensions take precedence so a server can override a built-in
            # endpoint with its own richer shape (e.g. urisys returns full route
            # dicts on /uri/routes) while still reusing the rest of the transport.
            handler = ext.get(f"GET {path}")
            if handler is not None:
                return handler(self, runtime)
            if path == "/health":
                return self._json(200, {"ok": True, "service": service, "runtime": "urisys-edge"})
            if path in ("/uri/routes", "/routes"):
                return self._json(200, {"ok": True, "routes": _routes_list(runtime)})
            if path.startswith("/events"):
                events = getattr(runtime, "events", None)
                tail: list[dict[str, Any]] = []
                if events is not None and hasattr(events, "tail"):
                    qs = parse_qs(urlparse(self.path).query)
                    limit = int((qs.get("n") or qs.get("limit") or ["50"])[0])
                    tail = events.tail(limit)
                return self._json(200, {"ok": True, "events": tail})
            return self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            handler = ext.get(f"POST {path}")
            if handler is not None:
                return handler(self, runtime)
            if path == "/uri/call":
                length = int(self.headers.get("Content-Length") or "0")
                body = self.rfile.read(length).decode("utf-8")
                req = json.loads(body or "{}")
                result = _as_dict(
                    runtime.call(
                        req.get("uri", ""),
                        req.get("payload") or {},
                        req.get("context") or {},
                    )
                )
                ok = result.get("ok", True) if isinstance(result, dict) else True
                return self._json(200 if ok else 400, result)
            return self._json(404, {"ok": False, "error": "not found"})

        def log_message(self, *args: Any) -> None:  # quiet by default
            pass

    return Handler


def serve(
    runtime: Any,
    host: str,
    port: int,
    *,
    service: str = "urisys",
    extensions: dict[str, ExtensionHandler] | None = None,
    cors: bool = False,
) -> None:
    server = ThreadingHTTPServer(
        (host, port),
        make_uri_handler(runtime, service=service, extensions=extensions, cors=cors),
    )
    print(f"{service}/urisys-edge listening on http://{host}:{port}")
    for pattern in _routes_list(runtime):
        print(" -", pattern)
    server.serve_forever()
