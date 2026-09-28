"""A tiny MCP server used only by tests. It has one read tool and one delete tool."""

import json
import sys

TOOLS = [
    {"name": "read_file", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}},
    {"name": "delete_file", "inputSchema": {"type": "object"}},
]

for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    if message["method"] == "tools/list":
        result = {"tools": TOOLS}
    elif message["method"] == "tools/call":
        result = {"content": [{"type": "text", "text": "ran " + message["params"]["name"]}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
