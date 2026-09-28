import json
import subprocess
import sys
from pathlib import Path

from control_room_proxy import Interceptor

HERE = Path(__file__).parent
PROXY = HERE.parent / "control_room_proxy.py"
FAKE_SERVER = HERE / "fake_server.py"


def tool_call(name: str) -> dict:
    return {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": {"path": "a.txt"}}}


def test_allowed_call_is_forwarded():
    interceptor = Interceptor("files", lambda *_: (True, "ok"))
    assert interceptor.from_client(tool_call("read_file")) == ("forward", tool_call("read_file"))


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
