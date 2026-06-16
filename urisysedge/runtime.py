from __future__ import annotations

import importlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

from .env import load_env_policy


def _result_ok(result: Any) -> bool:
    if isinstance(result, dict):
        if result.get("ok") is False:
            return False
        exit_code = result.get("exit_code")
        if exit_code is not None and exit_code != 0:
            return False
    return True


@dataclass
class Route:
    pattern: str
    kind: str
    operation: str
    handler_ref: str
    approval: str = "not_required"
    side_effects: bool = False
    _regex: re.Pattern | None = None

    def compile(self) -> "Route":
        parts: list[str] = []
        i = 0
        while i < len(self.pattern):
            if self.pattern[i] == "{":
                j = self.pattern.index("}", i)
                name = self.pattern[i + 1:j]
                parts.append(f"(?P<{name}>[^/]+)")
                i = j + 1
            else:
                parts.append(re.escape(self.pattern[i]))
                i += 1
        self._regex = re.compile("^" + "".join(parts) + "$")
        return self

    def match(self, uri: str) -> dict[str, str] | None:
        if self._regex is None:
            self.compile()
        assert self._regex is not None
        m = self._regex.match(uri)
        if not m:
            return None
        return {k: unquote(v) for k, v in m.groupdict().items()}


class JsonlEventStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict[str, Any]) -> None:
        row = dict(event)
        row.setdefault("event_id", str(uuid.uuid4()))
        row.setdefault("occurred_at_unix_ms", int(time.time() * 1000))
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def tail(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        out: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


class Runtime:
    def __init__(self, events_path: str | Path = "data/events.jsonl", config: dict[str, Any] | None = None):
        self.routes: list[Route] = []
        self.events = JsonlEventStore(events_path)
        self.config = config or {}
        self.state: dict[str, Any] = {}

    def register(
        self,
        pattern: str,
        handler: str,
        *,
        kind: str = "command",
        operation: str | None = None,
        approval: str = "not_required",
        side_effects: bool = False,
    ) -> None:
        op = operation or pattern.rsplit("/", 1)[-1]
        self.routes.append(Route(pattern, kind, op, handler, approval, side_effects).compile())

    def resolve(self, uri: str) -> tuple[Route, dict[str, str]]:
        for route in self.routes:
            params = route.match(uri)
            if params is not None:
                return route, params
        raise KeyError(f"No route for URI: {uri}")

    def _load_handler(self, ref: str) -> Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]:
        if ref.startswith("python://"):
            ref = ref[len("python://"):]
        module_name, func_name = ref.split(":", 1)
        mod = importlib.import_module(module_name)
        return getattr(mod, func_name)

    def call(self, uri: str, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        context = context or {}
        try:
            route, params = self.resolve(uri)
        except Exception as exc:
            return {"ok": False, "uri": uri, "type": "route_not_found", "error": str(exc)}

        approved = bool(context.get("approved"))
        if route.side_effects and route.approval == "required" and not approved:
            return {"ok": False, "uri": uri, "type": "policy_denied", "reason": "approval required"}

        ctx = dict(context)
        ctx.update({
            "uri": uri,
            "params": params,
            "config": self.config,
            "runtime": self,
            "state": self.state,
            "event_store": self.events,
        })
        if "env_config" not in ctx:
            policy = load_env_policy()
            if policy:
                ctx["env_config"] = policy
        event_base = {
            "event_id": str(uuid.uuid4()),
            "source_uri": uri,
            "operation": route.operation,
            "kind": route.kind,
            "params": params,
            "occurred_at_unix_ms": int(time.time() * 1000),
        }
        self.events.append({**event_base, "event_type": "operation.accepted", "payload": payload})
        try:
            handler = self._load_handler(route.handler_ref)
            result = handler(payload, ctx)
            ok = _result_ok(result)
            event = {**event_base, "event_id": str(uuid.uuid4()), "event_type": f"{route.operation}.completed", "result": result}
            self.events.append(event)
            return {"ok": ok, "uri": uri, "operation": route.operation, "params": params, "result": result, "event": event}
        except Exception as exc:
            event = {**event_base, "event_id": str(uuid.uuid4()), "event_type": f"{route.operation}.failed", "error": str(exc)}
            self.events.append(event)
            return {"ok": False, "uri": uri, "operation": route.operation, "error": str(exc), "event": event}


def load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    return json.loads(p.read_text(encoding="utf-8"))


def load_yaml_flow(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except Exception:
        # tiny fallback for simple examples
        data: dict[str, Any] = {"do": [], "defaults": {}}
        current = None
        active_item: dict[str, Any] | None = None
        for raw in text.splitlines():
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped in ("defaults:", "do:"):
                current = stripped[:-1]
                continue
            if current == "do" and stripped.startswith("- "):
                item = stripped[2:]
                if item.endswith(":"):
                    active_item = {item[:-1]: {}}
                    data["do"].append(active_item)
                else:
                    active_item = None
                    data["do"].append(item)
            elif current == "do" and active_item and ":" in stripped:
                key, value = stripped.split(":", 1)
                uri = next(iter(active_item.keys()))
                value = value.strip()
                if value.isdigit():
                    parsed: Any = int(value)
                elif value.lower() in ("true", "false"):
                    parsed = value.lower() == "true"
                else:
                    parsed = value
                active_item[uri][key.strip()] = parsed
        return data


def run_flow(runtime: Runtime, path: str, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    flow = load_yaml_flow(path)
    defaults = dict(flow.get("defaults") or {})
    if context:
        defaults.update(context)
    results = []
    for step in flow.get("do", []):
        if isinstance(step, str):
            uri, payload = step, {}
        elif isinstance(step, dict):
            uri, payload = next(iter(step.items()))
            payload = payload or {}
        else:
            raise ValueError(f"Invalid flow step: {step!r}")
        results.append(runtime.call(uri, payload, defaults))
    return results


def make_handler(runtime: Runtime):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, data: dict[str, Any]) -> None:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/health":
                return self._json(200, {"ok": True, "service": "urirdp", "runtime": "urisys-edge"})
            if self.path == "/uri/routes":
                return self._json(200, {"ok": True, "routes": [r.pattern for r in runtime.routes]})
            return self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            if self.path != "/uri/call":
                return self._json(404, {"ok": False, "error": "not found"})
            length = int(self.headers.get("Content-Length") or "0")
            body = self.rfile.read(length).decode("utf-8")
            req = json.loads(body or "{}")
            result = runtime.call(req.get("uri", ""), req.get("payload") or {}, req.get("context") or {})
            return self._json(200 if result.get("ok") else 400, result)

    return Handler


def serve(runtime: Runtime, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(runtime))
    print(f"urirdp/urisys-edge listening on http://{host}:{port}")
    print("routes:")
    for r in runtime.routes:
        print(" -", r.pattern)
    server.serve_forever()
