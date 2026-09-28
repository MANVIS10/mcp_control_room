import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from control_room_proxy import Interceptor, PolicyClient, main

HERE = Path(__file__).parent
PROXY = HERE.parent / "control_room_proxy.py"
FAKE_SERVER = HERE / "fake_server.py"


def tool_call(name: str) -> dict:
    return {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": {"path": "a.txt"}}}


def test_allowed_call_is_forwarded():
    interceptor = Interceptor("files", lambda *_: (True, "ok"))
    assert interceptor.from_client(tool_call("read_file")) == ("forward", tool_call("read_file"))


def test_approved_call_is_forwarded():
    interceptor = Interceptor("files", lambda *_: (True, "Approved by a human in Control Room."))
    assert interceptor.from_client(tool_call("delete_file")) == ("forward", tool_call("delete_file"))


def test_cancelled_call_is_dropped_even_if_approved_later():
    cancel = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 7}}

    def check(*_):
        # The client gives up while the human is still deciding; then the human approves.
        assert interceptor.from_client(cancel) == ("forward", cancel)
        return True, "Approved by a human in Control Room."

    interceptor = Interceptor("files", check)
    assert interceptor.from_client(tool_call("delete_file")) == ("drop", None)


def test_denied_call_never_reaches_the_server():
    interceptor = Interceptor("files", lambda *_: (False, "denied by you"))
    action, reply = interceptor.from_client(tool_call("delete_file"))
    assert action == "reply"
    assert reply["id"] == 7
    assert reply["result"]["isError"] is True
    assert "denied by you" in reply["result"]["content"][0]["text"]


def test_annotations_from_tools_list_are_passed_to_the_policy():
    seen = {}

    def check(server, tool, arguments, annotations):
        seen.update(annotations)
        return True, "ok"

    interceptor = Interceptor("files", check)
    interceptor.from_client({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    interceptor.from_server({"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "read_file", "annotations": {"readOnlyHint": True}}]}})
    interceptor.from_client(tool_call("read_file"))
    assert seen == {"readOnlyHint": True}


def test_proxy_fails_closed_when_control_room_is_down():
    messages = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, tool_call("read_file")]
    completed = subprocess.run(
        [sys.executable, str(PROXY), "--name", "files", "--api", "http://127.0.0.1:1", "--", sys.executable, str(FAKE_SERVER)],
        input="".join(json.dumps(m) + "\n" for m in messages),
        capture_output=True,
        text=True,
        timeout=60,
    )
    replies = {reply["id"]: reply for reply in map(json.loads, completed.stdout.splitlines())}
    assert [tool["name"] for tool in replies[1]["result"]["tools"]] == ["read_file", "delete_file"]
    assert replies[7]["result"]["isError"] is True
    assert "unreachable" in replies[7]["result"]["content"][0]["text"]


def test_policy_client_ignores_system_proxies(monkeypatch):
    class Stub(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps({"policy": "allowed", "reason": "ok"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = PolicyClient(f"http://127.0.0.1:{server.server_address[1]}")
        assert client.check("files", "read_file", {"path": "a.txt"}, {}) == (True, "ok")
    finally:
        server.shutdown()
        server.server_close()


def test_proxy_refuses_a_remote_api_address():
    with pytest.raises(SystemExit):
        main(["--name", "files", "--api", "http://example.com", "--", sys.executable, str(FAKE_SERVER)])
