"""Stdio MCP proxy.

Sits between an MCP client (Claude Desktop, Claude Code, Codex) and a real MCP server.
Every message passes straight through, except `tools/call`: before forwarding one,
the proxy asks the Control Room API and waits for a human decision when required.
If the API cannot be reached, the call is blocked (fail closed).
If the client cancels a call while it waits, the call is dropped even if it is approved later.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable


CheckFunction = Callable[[str, str, dict, dict], "tuple[bool, str]"]
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class PolicyClient:
    def __init__(self, base_url: str, timeout_seconds: float = 60.0, poll_seconds: float = 1.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        # Never send tool arguments through a system or environment proxy (HTTP_PROXY etc.).
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers={"Content-Type": "application/json"})
        with self.opener.open(request, timeout=10) as response:
            return json.loads(response.read())

    def check(self, server_name: str, tool_name: str, arguments: dict, annotations: dict) -> tuple[bool, str]:
        """Return (allowed, reason). Blocks until a human decides or the approval expires."""
        try:
            result = self._request("POST", "/api/tool-calls", {"server_name": server_name, "tool_name": tool_name, "arguments": arguments, "annotations": annotations})
            if result["policy"] == "allowed":
                return True, result["reason"]
            approval_id = result["approval"]["id"]
        except Exception:  # Fail closed: no answer from Control Room means no call.
            return False, "Control Room API is unreachable, so the call was blocked."

        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            time.sleep(self.poll_seconds)
            try:
                status = self._request("GET", f"/api/approvals/{approval_id}")["status"]
            except Exception:
                continue
            if status == "approved":
                return True, "Approved by a human in Control Room."
            if status in ("denied", "expired"):
                return False, f"The call was {status} in Control Room."
        return False, "Timed out waiting for a human decision."


class Interceptor:
    def __init__(self, server_name: str, check: CheckFunction) -> None:
        self.server_name = server_name
        self.check = check
        self.annotations: dict[str, dict] = {}
        self._tools_list_ids: set[Any] = set()
        self._cancelled_ids: set[Any] = set()
        self._lock = threading.Lock()

    def from_client(self, message: dict) -> tuple[str, dict | None]:
        """Return ("forward", message) to send it to the server, ("reply", response) to answer the client directly,
        or ("drop", None) when the client cancelled the call while it was waiting."""
        if message.get("method") == "tools/list" and "id" in message:
            with self._lock:
                self._tools_list_ids.add(message["id"])
        if message.get("method") == "notifications/cancelled":
            request_id = (message.get("params") or {}).get("requestId")
            if isinstance(request_id, (str, int)):
                with self._lock:
                    self._cancelled_ids.add(request_id)
        if message.get("method") != "tools/call":
            return "forward", message

        params = message.get("params") or {}
        tool_name = str(params.get("name", ""))
        arguments = params.get("arguments") or {}
        with self._lock:
            annotations = self.annotations.get(tool_name, {})
        allowed, reason = self.check(self.server_name, tool_name, arguments, annotations)
        with self._lock:
            cancelled = message.get("id") in self._cancelled_ids
            self._cancelled_ids.discard(message.get("id"))
        if cancelled:
            return "drop", None  # The client already gave up, so a late approval must not run the call.
        if allowed:
            return "forward", message
        return "reply", {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {"content": [{"type": "text", "text": f"Blocked by MCP Control Room: {reason}"}], "isError": True},
        }

    def from_server(self, message: dict) -> None:
        """Remember tool annotations from tools/list responses. They are untrusted hints."""
        with self._lock:
            if message.get("id") not in self._tools_list_ids:
                return
            self._tools_list_ids.discard(message.get("id"))
            for tool in (message.get("result") or {}).get("tools", []):
                if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                    annotations = tool.get("annotations")
                    self.annotations[tool["name"]] = annotations if isinstance(annotations, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Put MCP Control Room between an MCP client and a real MCP server.")
    parser.add_argument("--name", required=True, help="Server name shown in the Control Room dashboard.")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="Control Room API address.")
    parser.add_argument("--allow-remote-api", action="store_true", help="Allow an --api address that is not on this computer.")
    parser.add_argument("--timeout", type=float, default=60.0, help="Seconds to wait for a human decision.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="The real MCP server command, after --")
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("put the real MCP server command after --")
    if urllib.parse.urlparse(args.api).hostname not in LOOPBACK_HOSTS and not args.allow_remote_api:
        parser.error("--api must be on this computer (127.0.0.1, localhost or ::1); add --allow-remote-api to override")

    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    interceptor = Interceptor(args.name, PolicyClient(args.api, timeout_seconds=args.timeout).check)
    server = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
    client_lock, server_lock = threading.Lock(), threading.Lock()

    def send_to_client(message: Any) -> None:
        with client_lock:
            sys.stdout.write(json.dumps(message) + "\n")
            sys.stdout.flush()

    def send_to_server(message: Any) -> None:
        with server_lock:
            server.stdin.write(json.dumps(message) + "\n")
            server.stdin.flush()

    def pump_server_output() -> None:
        for line in server.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # MCP servers must write only JSON-RPC to stdout.
            if isinstance(message, dict):
                interceptor.from_server(message)
            send_to_client(message)

    def handle(message: dict) -> None:
        action, outgoing = interceptor.from_client(message)
        if action == "forward":
            send_to_server(outgoing)
        elif action == "reply":
            send_to_client(outgoing)

    pump = threading.Thread(target=pump_server_output, daemon=True)
    pump.start()
    waiting_calls: list[threading.Thread] = []
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            send_to_client({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Batch requests are not supported by MCP Control Room."}})
        elif message.get("method") == "tools/call":
            # Wait for the human on a separate thread so other traffic keeps flowing.
            thread = threading.Thread(target=handle, args=(message,), daemon=True)
            thread.start()
            waiting_calls.append(thread)
        else:
            handle(message)

    for thread in waiting_calls:
        thread.join()
    server.stdin.close()
    exit_code = server.wait()
    pump.join(timeout=5)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
