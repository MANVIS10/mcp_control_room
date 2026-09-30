"""Command line entry point: `mcp-control-room` (serve) and `mcp-control-room config`."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

DEFAULT_PORT = 8000


def dashboard_url(port: int, token: str) -> str:
    # The token sits in the #fragment, which browsers never send to a server or write to access logs.
    return f"http://127.0.0.1:{port}/#token={token}"


def config_snippet(name: str, folder: Path, port: int) -> dict:
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    return {"mcpServers": {f"{name}-guarded": {
        "command": sys.executable,
        "args": ["-m", "control_room_proxy", "--name", name, "--api", f"http://127.0.0.1:{port}", "--", npx, "-y", "@modelcontextprotocol/server-filesystem", str(folder)],
    }}}


def serve(port: int) -> int:
    import uvicorn

    data_dir = Path.home() / ".mcp-control-room"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MCP_CONTROL_DATABASE_URL", f"sqlite:///{(data_dir / 'control-room.db').as_posix()}")
    token = os.environ.get("MCP_CONTROL_APPROVER_TOKEN") or secrets.token_urlsafe(24)
    os.environ["MCP_CONTROL_APPROVER_TOKEN"] = token

    print(f"\nMCP Control Room is starting.\n\n  Open the dashboard (unlocks approvals):\n  {dashboard_url(port, token)}\n", flush=True)
    print("  Next: in another terminal run `mcp-control-room config` and paste the JSON into Claude Desktop or Cursor.\n", flush=True)
    from .main import app  # imported late so the env vars above are already set

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mcp-control-room", description="Human-in-the-loop approval gateway for MCP tool calls.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port for the dashboard and API (default 8000).")
    commands = parser.add_subparsers(dest="command")
    config = commands.add_parser("config", help="Print a ready-to-paste Claude Desktop / Cursor config for a guarded filesystem server.")
    config.add_argument("--name", default="files", help="Name shown in the dashboard.")
    config.add_argument("--dir", type=Path, default=Path.home() / "mcp-sandbox", help="Folder the guarded server may access (default ~/mcp-sandbox).")
    config.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port the API runs on.")
    args = parser.parse_args(argv)

    if args.command == "config":
        args.dir.mkdir(parents=True, exist_ok=True)
        print(json.dumps(config_snippet(args.name, args.dir.resolve(), args.port), indent=2))
        return 0
    return serve(args.port)


if __name__ == "__main__":
    sys.exit(main())
