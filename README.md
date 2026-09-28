# MCP Control Room

A human-in-the-loop security gateway for AI agents: risky MCP tool calls pause until you approve them.

<!-- Recorded by hand after Task 9; the image is broken until that recording exists. -->
![demo](assets/demo.gif)

A local-first dashboard and policy gateway for Model Context Protocol servers.

It inventories Codex and Claude-compatible MCP configurations, streams sanitized activity to a React dashboard, evaluates project-fit and risk, requires human approval for consequential calls, and learns only from explicit feedback.

## How it works

```
 Claude Code / Claude Desktop
          │  (wants to run a tool, e.g. delete_file)
          ▼
 ┌──────────────────────┐   "is this ok?"   ┌─────────────────────┐   live updates   ┌──────────────┐
 │  control_room_proxy  │ ────────────────► │  FastAPI API        │ ───────────────► │  Dashboard   │
 │  (apps/proxy)        │ ◄──────────────── │  rules + database   │ ◄─────────────── │  (you click  │
 └──────────────────────┘  allowed/denied   └─────────────────────┘  Approve/Deny    │  Approve)    │
          │  only if allowed                                                         └──────────────┘
          ▼
 Real MCP server (e.g. the filesystem server)
```

The proxy sits between an AI assistant and a real MCP server. Read calls go straight through. Write, delete, network and shell calls pause and wait for a human to approve or deny them in the dashboard, over live Server-Sent Events.

## Try it

Prerequisites: the API and dashboard are installed (see "Local development setup" below) and `claude` (Claude Code) is on your machine.

1. **Start the API** (terminal 1, with the venv active):
   ```powershell
   py -m uvicorn app.main:app --app-dir apps/api --reload --env-file .env
   ```
2. **Start the dashboard** (terminal 2):
   ```powershell
   Set-Location apps/web
   npm.cmd run dev
   ```
   Open http://localhost:5173. You should see **● Live** in the top right.
3. **Register the guarded server with Claude Code** (terminal 3). This is all one command:
   ```powershell
   claude mcp add files-guarded -- C:\Users\sonim\mcp_control_rom\.venv\Scripts\python.exe C:\Users\sonim\mcp_control_rom\apps\proxy\control_room_proxy.py --name files -- npx.cmd -y @modelcontextprotocol/server-filesystem C:\Users\sonim\mcp-sandbox
   ```
   Everything after the first `--` is the command Claude Code will run (your proxy). Everything after the second `--` is the real server the proxy starts.
4. **Test three cases.** Start `claude` in a new terminal and ask:
   1. *"Use files-guarded to read hello.txt in the sandbox."* The read goes straight through; the audit trail shows `tool_call.allowed`.
   2. *"Use files-guarded to write a file called notes.txt saying hi."* The request appears in the **Approval queue** with a countdown. Click **Approve**. The AI reports success and `notes.txt` now exists.
   3. Ask it to write another file, then click **Deny**. The AI is told the call was blocked, and the file is **not** created.

The real filesystem MCP server marks its read tools as read-only, so reads go straight through while writes wait for approval — this was verified live, not just in unit tests.

## Architecture decision record — initial pushback

The proposed stack is sound, with three corrections that keep it reliable:

1. **LangGraph is not the authorization layer.** Use it only for explainable advisory workflows (judge, recommender, end-of-day summary). Risk classification and approval enforcement must be deterministic FastAPI policy code, otherwise an injected description could influence execution.
2. **Do not start by "running natively" inside Codex and Claude.** Their config formats, installation locations, and lifecycle hooks vary. Begin with read-only adapters that import selected config files into a normalized inventory. Add controlled launch/proxy adapters after compatibility tests.
3. **SQLite is right locally, but write SSE events through one API process.** SQLite + multiple API workers can cause lock contention. Start with one worker and a bounded in-memory event fan-out; move to a broker only when multi-process deployment is real.

## Product agents

| Capability | Role | Execution boundary | Status |
| --- | --- | --- | --- |
| Connection discovery | Imports selected Codex/Claude configs | Read-only adapters | Built |
| Initializer | Produces frontend read model | API + SSE | Built |
| Judge | Scores current-project relevance | Advisory, no execution | Planned |
| Recommender | Ranks suggested actions and explains why | Advisory, feedback-aware | Planned |
| Action | Enacts a user-approved command | Policy-gated only | Built |
| Learning | Updates preference signals from feedback | Explicit feedback only | Planned |
| EOD update | Summarizes captured activity on request | Read-only aggregation | Planned |
| Cost analyst | Estimates token/tool cost and optimization options | Advisory, estimates labeled | Planned |

The audit trail — every tool-call summary, risk decision and approval, with actor/time metadata and secrets redacted — is also **Built**.

## Planned layout

```text
apps/
  api/              FastAPI policy gateway and adapters
  web/              React + TypeScript dashboard
packages/
  contracts/        shared schemas and event names
.agents/skills/     project-specific agent playbooks
data/               local SQLite runtime state (gitignored)
```

## What works today

- The stdio proxy gates every `tools/call`, not just a demo path.
- Deterministic risk rules: server-supplied metadata can raise risk but never lower it, and unknown tools default to approval.
- Approvals expire; an unanswered request is blocked, not allowed (fail closed).
- Secret redaction, so tokens and keys never reach logs, the audit trail or the SSE broadcast.
- A live SSE dashboard with Approve/Deny, reconnect replay, and an audit trail.
- 26 automated tests, plus CI on GitHub Actions.

## Known limits

- Not a sandbox: an approved call still runs with the real MCP server's full permissions. Real isolation belongs in containers, not this project.
- Risk rules are word-based, so a misleadingly named tool that also claims to be read-only could slip through. The trusted-read list exists for this reason.
- Stdio servers only — no HTTP/SSE MCP servers yet.
- A client may give up waiting on a slow approval before a human decides.

## Local development setup

Prerequisites: Python 3.11+ (with `pip`) and Node.js 20+. On this Windows machine, call npm as `npm.cmd` because PowerShell's execution policy blocks `npm.ps1`.

```powershell
Copy-Item .env.example .env
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r apps/api/requirements.txt
py -m uvicorn app.main:app --app-dir apps/api --reload --env-file .env
```

For API tests, install the development dependencies once:

```powershell
py -m pip install -r apps/api/requirements-dev.txt
py -m pytest
```
Run this from the project root (not `apps/api`); `pytest.ini` points it at the right packages.

In a second terminal, run the React dashboard:

```powershell
Set-Location apps/web
npm.cmd install
npm.cmd run dev
```

No Docker setup is used. No credentials should be placed in the frontend environment file or committed to git.
