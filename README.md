# MCP Control Room

A local-first dashboard and policy gateway for Model Context Protocol servers.

It inventories Codex and Claude-compatible MCP configurations, streams sanitized activity to a React dashboard, evaluates project-fit and risk, requires human approval for consequential calls, and learns only from explicit feedback.

## Architecture decision record — initial pushback

The proposed stack is sound, with three corrections that keep it reliable:

1. **LangGraph is not the authorization layer.** Use it only for explainable advisory workflows (judge, recommender, end-of-day summary). Risk classification and approval enforcement must be deterministic FastAPI policy code, otherwise an injected description could influence execution.
2. **Do not start by "running natively" inside Codex and Claude.** Their config formats, installation locations, and lifecycle hooks vary. Begin with read-only adapters that import selected config files into a normalized inventory. Add controlled launch/proxy adapters after compatibility tests.
3. **SQLite is right locally, but write SSE events through one API process.** SQLite + multiple API workers can cause lock contention. Start with one worker and a bounded in-memory event fan-out; move to a broker only when multi-process deployment is real.

## Product agents

| Capability | Role | Execution boundary |
| --- | --- | --- |
| Connection discovery | Imports selected Codex/Claude configs | Read-only adapters |
| Initializer | Produces frontend read model | API + SSE |
| Judge | Scores current-project relevance | Advisory, no execution |
| Recommender | Ranks suggested actions and explains why | Advisory, feedback-aware |
| Action | Enacts a user-approved command | Policy-gated only |
| Learning | Updates preference signals from feedback | Explicit feedback only |
| EOD update | Summarizes captured activity on request | Read-only aggregation |
| Cost analyst | Estimates token/tool cost and optimization options | Advisory, estimates labeled |

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

## First vertical slice

1. Import one user-selected configuration file without mutating it.
2. Render connections and a live, redacted event feed over SSE.
3. Intercept a simulated delete-class call and require approval/denial.
4. Persist the decision and show it in the audit trail.
5. Add project-fit and cost recommendations as clearly labeled advice.

## Local development setup

Prerequisites: Python 3.11+ (with `pip`) and Node.js 20+. On this Windows machine, call npm as `npm.cmd` because PowerShell's execution policy blocks `npm.ps1`.

```powershell
Copy-Item .env.example .env
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r apps/api/requirements.txt
py -m uvicorn app.main:app --app-dir apps/api --reload
```

For API tests, install the development dependencies once:

```powershell
py -m pip install -r apps/api/requirements-dev.txt
py -m pytest apps/api/tests
```

In a second terminal, run the React dashboard:

```powershell
Set-Location apps/web
npm.cmd install
npm.cmd run dev
```

No Docker setup is used. No credentials should be placed in the frontend environment file or committed to git.
