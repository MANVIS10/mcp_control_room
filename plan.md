# MCP Control Room — Build Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current prototype into a working security gateway that sits between a real AI assistant and a real MCP server, and makes risky tool calls wait for your Approve/Deny click.

**Architecture:** A small Python **proxy** is started by your AI assistant instead of the real MCP server. The proxy passes every message through, except "run this tool" messages (`tools/call`). For those it asks the **FastAPI** control plane. The API decides the risk with plain code rules and, if needed, holds the call until you click Approve or Deny in the **React** dashboard. Everything is logged to **SQLite** with secrets masked.

**Tech Stack:** Python 3.11, FastAPI, SQLite, pytest · React 19 + TypeScript + Vite · Server-Sent Events · MCP (JSON-RPC over stdio)

**Spec:** `AGENTS.md` (product rules) and `README.md` (architecture). This plan follows both.

## Global Constraints

- The final allow/block decision is made by plain code, never by an LLM. (AGENTS.md)
- Text from MCP servers (tool names, descriptions, hints) is untrusted. It may **raise** risk but must never **lower** it.
- Secrets are masked **before** anything is saved to the database or sent to the dashboard.
- If the Control Room can't be reached, calls are **blocked** ("fail closed"), never let through.
- Config files are only ever **read**, never changed.
- Windows: call npm as `npm.cmd` and npx as `npx.cmd` (PowerShell blocks the `.ps1` versions).
- Python 3.11+, Node.js 20+.

---

## Read this first (plain English)

**What you are building, in one picture:**

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

**What you have today:** the dashboard and API exist, but nothing real passes through them. You have to call the API by hand and *tell* it how risky your call is. Approving does nothing.

**What you'll have at the end:**
1. A real AI assistant, talking to a real MCP server, **through your proxy**.
2. Read calls go straight through. Delete, write and run-command calls **pause** until you click in the dashboard.
3. Secrets like API keys and tokens are masked everywhere.
4. Requests nobody answers **expire** and are blocked.
5. Every browser tab gets live updates.
6. 25 automated tests, CI on GitHub, and a demo GIF for your README.

**How to use this plan:**
- Do the tasks **in order**. Each one ends with the tests passing and a git commit.
- Tick the `- [ ]` boxes as you go (change them to `- [x]`).
- Wherever a step says "create" or "replace", copy the code block **exactly**.
- Each task starts with "Why", which you can reuse to explain your choices in interviews.
- Every command runs in **PowerShell** from the project folder `C:\Users\sonim\mcp_control_rom`, unless a step says otherwise.
- If a test fails, read the error from the bottom up. The last lines usually name the file and line.

**Words you'll see:**
| Word | Meaning |
|---|---|
| MCP server | A small program that gives an AI new abilities ("tools"), like reading files. |
| `tools/list` / `tools/call` | The two MCP messages that matter here: "what tools do you have?" and "run this tool". |
| JSON-RPC over stdio | MCP messages are one JSON object per line, sent through a program's standard input/output. |
| Proxy | A middleman that passes messages along and can stop some of them. |
| Fail closed | If something breaks, block the action instead of allowing it. |
| SSE | Server-Sent Events: the server pushes live updates to the browser. |
| Redaction | Replacing secret values with `[REDACTED]`. |

---

### Task 0: Get set up and make the tests run from the project root

**Why:** Right now `py -m pytest apps/api/tests` fails with `No module named 'app'` because pytest doesn't know where the code lives. There's also no git history yet. You need both before you change anything.

**Files:**
- Create: `pytest.ini`

- [ ] **Step 1: Start git**

```powershell
git init
git add .
git commit -m "chore: import existing prototype"
```
Expected: a commit is created. `git status` shows "nothing to commit". (The `.gitignore` already keeps `.venv`, `node_modules`, `.env` and the database out.)

- [ ] **Step 2: Turn on the virtual environment and install test tools**

```powershell
.\.venv\Scripts\Activate.ps1
py -m pip install -r apps/api/requirements-dev.txt
```
Expected: your prompt starts with `(.venv)`. Do this in **every new terminal** before running Python commands.

- [ ] **Step 3: Create `pytest.ini`** in the project root

```ini
[pytest]
pythonpath = apps/api apps/proxy
testpaths = apps/api/tests apps/proxy/tests
```

This tells pytest where the code lives (`pythonpath`) and where the tests are (`testpaths`). `apps/proxy` doesn't exist yet. It gets created in Task 5.

- [ ] **Step 4: Create the proxy test folder so pytest doesn't complain**

```powershell
New-Item -ItemType Directory -Force apps/proxy/tests
```

- [ ] **Step 5: Run the tests**

```powershell
py -m pytest
```
Expected: `3 passed`.

- [ ] **Step 6: Commit**

```powershell
git add pytest.ini
git commit -m "test: run pytest from the project root"
```

---

### Task 1: Mask secrets (redaction)

**Why:** The README promises "redacted" events, but no redaction code exists. `.env.example` lists `MCP_CONTROL_REDACTION_KEYS`, but nothing reads it. If an AI calls a tool with `{"api_key": "sk-..."}`, that key would be saved in plain text in SQLite. This task adds one small module that masks secrets in two ways:
1. **By key name:** any field whose name contains `token`, `password`, `secret`, `api_key` and so on becomes `[REDACTED]`, however deeply it's nested.
2. **By shape:** values that *look* like tokens (`Bearer ...`, `sk-...`, `ghp_...`) are masked even under an innocent key like `note`.

**Files:**
- Create: `apps/api/app/redaction.py`
- Test: `apps/api/tests/test_redaction.py`

**Interfaces:**
- Produces: `redact(value) -> same shape with secrets masked`, `redact_text(text: str) -> str`, `preview(arguments: dict) -> str` (redacted JSON, max 300 characters). Task 4 uses all three.

- [ ] **Step 1: Write the failing test.** Create `apps/api/tests/test_redaction.py`:

```python
from app.redaction import MASK, preview, redact


def test_secret_keys_are_masked_at_any_depth():
    data = {"path": "notes.txt", "headers": {"Authorization": "Bearer abc123"}, "items": [{"api_key": "k-1"}]}
    assert redact(data) == {"path": "notes.txt", "headers": {"Authorization": MASK}, "items": [{"api_key": MASK}]}


def test_token_shaped_values_are_masked_even_under_innocent_keys():
    assert "ghp_" not in preview({"note": "use ghp_abcdefghijklmnop to push"})
    assert "abc.def" not in preview({"note": "header was Bearer abc.def"})


def test_long_previews_are_truncated():
    assert len(preview({"text": "x" * 1000})) == 300


def test_key_names_match_regardless_of_separators():
    data = {"X-Api-Key": "abc123", "api.key": "def456", "Auth-Token": "ghi789"}
    assert redact(data) == {"X-Api-Key": MASK, "api.key": MASK, "Auth-Token": MASK}
```

- [ ] **Step 2: Run it and watch it fail**

```powershell
py -m pytest apps/api/tests/test_redaction.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.redaction'`. That's good: it proves the test is really checking something.

- [ ] **Step 3: Write the code.** Create `apps/api/app/redaction.py`:

```python
"""Remove secret values before anything is stored in SQLite or sent over SSE."""

from __future__ import annotations

import json
import os
import re
from typing import Any


DEFAULT_KEYS = "api_key,apikey,authorization,password,secret,token"
MASK = "[REDACTED]"
MAX_PREVIEW_CHARS = 300
TOKEN_PATTERNS = [
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"),
    re.compile(r"\b(?:sk|ghp|gho|github_pat|xox[abp])[-_][A-Za-z0-9_\-]{8,}"),
]


def normalise(text: str) -> str:
    """Remove non-alphanumeric characters and lowercase."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def sensitive_keys() -> set[str]:
    raw = os.getenv("MCP_CONTROL_REDACTION_KEYS") or DEFAULT_KEYS
    return {normalise(key.strip()) for key in raw.split(",") if key.strip()}


def redact_text(text: str) -> str:
    for pattern in TOKEN_PATTERNS:
        text = pattern.sub(MASK, text)
    return text


def redact(value: Any, keys: set[str] | None = None) -> Any:
    keys = sensitive_keys() if keys is None else keys
    if isinstance(value, dict):
        return {k: MASK if any(s in normalise(str(k)) for s in keys) else redact(v, keys) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, keys) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def preview(arguments: dict) -> str:
    text = json.dumps(redact(arguments), ensure_ascii=False, default=str)
    return text if len(text) <= MAX_PREVIEW_CHARS else text[: MAX_PREVIEW_CHARS - 1] + "…"
```

How it works: `redact` walks through dicts and lists. For a dict key that *contains* a sensitive word (separators like `-`, `_`, `.` are ignored when matching), it swaps the whole value for `[REDACTED]`. For any string, it runs the token patterns over it. Masking too much is safe; masking too little leaks secrets.

- [ ] **Step 4: Run the test again**

```powershell
py -m pytest apps/api/tests/test_redaction.py -v
```
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/app/redaction.py apps/api/tests/test_redaction.py
git commit -m "feat(api): add secret redaction helpers"
```

---

### Task 2: Live updates that reach every browser tab

**Why:** Today there's **one** shared queue (`event_queue` in `main.py`). With two dashboard tabs open, each event is taken by only **one** of them, so the other tab misses it. The fix is a small "broadcaster" that gives each connected tab its own queue and copies every event into all of them. It also keeps the last 100 events, so a tab that briefly disconnects can catch up. (Browsers send a `Last-Event-ID` header automatically when they reconnect.)

**Files:**
- Create: `apps/api/app/events.py`
- Test: `apps/api/tests/test_events.py`

**Interfaces:**
- Produces: `class Broadcaster(buffer_size=500, history_size=100)` with `subscribe(last_event_id: str | None) -> asyncio.Queue`, `unsubscribe(queue)`, and `publish(event: dict)`. Events are dicts with an `"id"` key. Task 4 uses this.

- [ ] **Step 1: Write the failing test.** Create `apps/api/tests/test_events.py`:

```python
from app.events import Broadcaster


def event(event_id: str) -> dict:
    return {"id": event_id, "type": "test", "at": "now", "data": {}}


def test_every_subscriber_receives_every_event():
    broadcaster = Broadcaster()
    first, second = broadcaster.subscribe(), broadcaster.subscribe()
    broadcaster.publish(event("1"))
    assert first.get_nowait()["id"] == "1"
    assert second.get_nowait()["id"] == "1"


def test_reconnecting_client_gets_missed_events():
    broadcaster = Broadcaster()
    for event_id in ("1", "2", "3"):
        broadcaster.publish(event(event_id))
    queue = broadcaster.subscribe(last_event_id="1")
    assert [queue.get_nowait()["id"], queue.get_nowait()["id"]] == ["2", "3"]


def test_unsubscribed_client_stops_receiving():
    broadcaster = Broadcaster()
    queue = broadcaster.subscribe()
    broadcaster.unsubscribe(queue)
    broadcaster.publish(event("1"))
    assert queue.empty()
```

- [ ] **Step 2: Run it and watch it fail**

```powershell
py -m pytest apps/api/tests/test_events.py -v
```
Expected: FAIL with `No module named 'app.events'`.

- [ ] **Step 3: Write the code.** Create `apps/api/app/events.py`:

```python
"""In-memory SSE fan-out: every connected browser tab gets its own queue."""

from __future__ import annotations

import asyncio
from collections import deque


class Broadcaster:
    def __init__(self, buffer_size: int = 500, history_size: int = 100) -> None:
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self._history: deque[dict] = deque(maxlen=history_size)
        self._buffer_size = buffer_size

    def subscribe(self, last_event_id: str | None = None) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self._buffer_size)
        ids = [event["id"] for event in self._history]
        if last_event_id in ids:
            for event in list(self._history)[ids.index(last_event_id) + 1 :]:
                queue.put_nowait(event)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: dict) -> None:
        self._history.append(event)
        for queue in list(self._subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)
```

- [ ] **Step 4: Run the test again**

```powershell
py -m pytest apps/api/tests/test_events.py -v
```
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/app/events.py apps/api/tests/test_events.py
git commit -m "feat(api): fan out live events to every dashboard tab"
```

---

### Task 3: Risk rules that don't trust the caller

**Why:** Today the caller *tells* the API how risky a call is (`"capability": "read"`), so anything can just claim to be a read. The API must decide for itself, using plain code, from three things:
1. **The tool name**, split into words (`deleteRepo` → `delete`, `repo`).
2. **The arguments.** A URL means network access. A `command` argument means running a program.
3. **The server's hints** (`readOnlyHint`, `destructiveHint`). These come from the server, so they are **untrusted**. They can make a call *more* risky, never less.

The rules check the most dangerous categories first: delete → credential → execute → network → write. A call runs without approval **only** if its name reads like a read **and** the server marks it read-only, **or** you personally listed it in `MCP_CONTROL_TRUSTED_READ_TOOLS`. Anything unknown waits for a human.

**Files:**
- Create: `apps/api/app/policy.py`
- Test: `apps/api/tests/test_rules.py`

**Interfaces:**
- Produces: `classify(server_name: str, tool_name: str, arguments: dict, annotations: dict) -> Decision`, where `Decision` has `.capability` (one of `read/write/execute/network/credential/delete`), `.requires_approval: bool` and `.reason: str`. Task 4 uses it.

- [ ] **Step 1: Write the failing test.** Create `apps/api/tests/test_rules.py`:

```python
from app.policy import classify


def test_read_needs_both_a_read_name_and_a_read_only_hint():
    assert classify("files", "read_file", {"path": "a.txt"}, {"readOnlyHint": True}).requires_approval is False
    assert classify("files", "read_file", {"path": "a.txt"}, {}).requires_approval is True


def test_server_hints_cannot_make_a_delete_safe():
    decision = classify("files", "delete_file", {"path": "a.txt"}, {"readOnlyHint": True})
    assert decision.capability == "delete"
    assert decision.requires_approval is True


def test_arguments_can_raise_risk():
    assert classify("x", "get_page", {"url": "https://evil.example"}, {"readOnlyHint": True}).capability == "network"
    assert classify("x", "helper", {"command": "rm -rf /"}, {}).capability == "execute"


def test_camel_case_names_are_split():
    assert classify("x", "deleteRepo", {}, {}).capability == "delete"


def test_unknown_tools_require_approval():
    assert classify("x", "frobnicate", {}, {}).requires_approval is True


def test_user_can_trust_a_specific_read_tool(monkeypatch):
    monkeypatch.setenv("MCP_CONTROL_TRUSTED_READ_TOOLS", "files:directory_tree")
    assert classify("files", "directory_tree", {"path": "."}, {}).requires_approval is False
    assert classify("other", "directory_tree", {"path": "."}, {}).requires_approval is True
```

Look at `test_server_hints_cannot_make_a_delete_safe`. This is your **prompt-injection test**: a lying server says "I'm read-only" about a delete tool, and the rules ignore it.

- [ ] **Step 2: Run it and watch it fail**

```powershell
py -m pytest apps/api/tests/test_rules.py -v
```
Expected: FAIL with `No module named 'app.policy'`.

- [ ] **Step 3: Write the code.** Create `apps/api/app/policy.py`:

```python
"""Deterministic risk rules. No LLM and no server-provided text can lower a risk decision."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterator, Literal


Capability = Literal["read", "write", "execute", "network", "credential", "delete"]

DELETE_WORDS = {"delete", "remove", "drop", "destroy", "purge", "erase", "rm", "unlink", "truncate"}
CREDENTIAL_WORDS = {"secret", "secrets", "credential", "credentials", "token", "tokens", "password", "passwords", "auth", "login"}
EXECUTE_WORDS = {"exec", "execute", "run", "shell", "command", "eval", "spawn", "terminal", "script"}
NETWORK_WORDS = {"fetch", "http", "request", "send", "email", "webhook", "upload", "publish", "navigate", "browse", "post"}
WRITE_WORDS = {"write", "create", "edit", "update", "move", "rename", "set", "put", "insert", "append", "patch", "save", "commit", "push", "merge"}
READ_WORDS = {"read", "list", "get", "search", "find", "query", "describe", "show", "view"}
EXECUTE_ARGUMENT_KEYS = {"command", "cmd", "script", "shell"}


@dataclass(frozen=True)
class Decision:
    capability: Capability
    requires_approval: bool
    reason: str


def words(tool_name: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", tool_name)
    return {word for word in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if word}


def string_values(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for item in value.values():
            yield from string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from string_values(item)
    elif isinstance(value, str):
        yield value


def trusted_read_tools() -> set[str]:
    """User-chosen 'server:tool' pairs that are allowed as reads without approval."""
    raw = os.getenv("MCP_CONTROL_TRUSTED_READ_TOOLS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def classify(server_name: str, tool_name: str, arguments: dict, annotations: dict) -> Decision:
    name_words = words(tool_name)
    argument_keys = {str(key).lower() for key in arguments}
    has_url = any(value.lower().startswith(("http://", "https://")) for value in string_values(arguments))

    # Most dangerous first. The first matching rule wins.
    if name_words & DELETE_WORDS or annotations.get("destructiveHint") is True:
        return Decision("delete", True, "Deletes or destroys data.")
    if name_words & CREDENTIAL_WORDS:
        return Decision("credential", True, "Touches secrets or credentials.")
    if name_words & EXECUTE_WORDS or argument_keys & EXECUTE_ARGUMENT_KEYS:
        return Decision("execute", True, "Runs a command or program.")
    if name_words & NETWORK_WORDS or has_url:
        return Decision("network", True, "Talks to the network or an outside service.")
    if name_words & WRITE_WORDS:
        return Decision("write", True, "Changes data.")
    if f"{server_name}:{tool_name}" in trusted_read_tools():
        return Decision("read", False, "You marked this tool as a trusted read.")
    if name_words & READ_WORDS and annotations.get("readOnlyHint") is True:
        return Decision("read", False, "Read-style name and the server marks it read-only.")
    return Decision("write", True, "Unknown behaviour, so a human must decide.")
```

- [ ] **Step 4: Run the test again**

```powershell
py -m pytest apps/api/tests/test_rules.py -v
```
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/app/policy.py apps/api/tests/test_rules.py
git commit -m "feat(api): deterministic risk rules from name, arguments and hints"
```

---

### Task 4: Only read config files from folders you allow

**Why:** `.env.example` has `MCP_CONTROL_ALLOWED_CONFIG_ROOTS`, but nothing checks it. Today the import endpoint will open **any** file path it's given. After this task, it only reads inside the folders you list (separated by `;` on Windows). If you list nothing, it defaults to your home folder.

**Files:**
- Modify: `apps/api/app/adapters.py`
- Test: `apps/api/tests/test_adapters.py`

- [ ] **Step 1: Write the failing test.** Create `apps/api/tests/test_adapters.py`:

```python
import pytest

from app.adapters import ConfigImportError, import_config


def write_config(folder):
    config = folder / "config.toml"
    config.write_text('[mcp_servers.files]\ncommand = "npx"\n')
    return config


def test_import_inside_an_allowed_folder_works(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_CONTROL_ALLOWED_CONFIG_ROOTS", str(tmp_path))
    _, servers = import_config(str(write_config(tmp_path)), "codex")
    assert [(server.name, server.transport) for server in servers] == [("files", "stdio")]


def test_import_outside_allowed_folders_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_CONTROL_ALLOWED_CONFIG_ROOTS", str(tmp_path / "somewhere-else"))
    with pytest.raises(ConfigImportError, match="outside the allowed"):
        import_config(str(write_config(tmp_path)), "codex")
```

- [ ] **Step 2: Run it and watch it fail**

```powershell
py -m pytest apps/api/tests/test_adapters.py -v
```
Expected: `test_import_outside_allowed_folders_is_refused` FAILS with `DID NOT RAISE`. The other test passes.

- [ ] **Step 3: Change `apps/api/app/adapters.py`.** Near the top, add `import os`, so the imports read:

```python
import json
import os
import tomllib
```

Then find the start of `import_config`:

```python
def import_config(path_value: str, source: Source) -> tuple[Path, list[ImportedConnection]]:
    """Parse a user-selected file without expanding env vars or launching a server."""
    path = Path(path_value).expanduser().resolve(strict=True)
```

and replace those three lines with:

```python
def allowed_roots() -> list[Path]:
    """Folders the importer may read from. Empty setting means your home folder only."""
    raw = os.getenv("MCP_CONTROL_ALLOWED_CONFIG_ROOTS", "")
    roots = [Path(item).expanduser().resolve() for item in raw.split(os.pathsep) if item.strip()]
    return roots or [Path.home().resolve()]


def import_config(path_value: str, source: Source) -> tuple[Path, list[ImportedConnection]]:
    """Parse a user-selected file without expanding env vars or launching a server."""
    path = Path(path_value).expanduser().resolve(strict=True)
    if not any(path.is_relative_to(root) for root in allowed_roots()):
        raise ConfigImportError("The selected file is outside the allowed configuration folders.")
```

Leave the rest of the file unchanged. `resolve()` turns tricks like `..\..\` into a real path *before* the check, so they can't escape the allowed folder.

- [ ] **Step 4: Run the test again**

```powershell
py -m pytest apps/api/tests/test_adapters.py -v
```
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/app/adapters.py apps/api/tests/test_adapters.py
git commit -m "feat(api): restrict config imports to allowed folders"
```

---

### Task 5: Wire everything into the API (new tool-call contract, expiry, polling)

**Why:** This connects Tasks 1–3 to the actual endpoints:
- `POST /api/tool-calls` now receives **what the AI actually wants to do** (`tool_name`, `arguments`, server `annotations`) and decides the risk itself using `classify`. The old self-declared `capability` field is **removed**.
- Every approval gets an **expiry time** (default 120 seconds). A request nobody answers becomes `expired` and is blocked.
- New `GET /api/approvals/{id}` lets the proxy (Task 6) check whether you've decided yet.
- Everything saved or streamed first goes through `redact`/`preview`.
- The SSE endpoint uses the `Broadcaster` and cleans up when a tab closes.
- The database gets three new approval columns (`tool_name`, `arguments_preview`, `expires_at`). They are added automatically on start-up, so your existing `data/mcp-control-room.db` keeps working.

**Files:**
- Replace: `apps/api/app/main.py`
- Replace: `apps/api/tests/test_policy.py`

**Interfaces:**
- Consumes: `redact`, `redact_text`, `preview` (Task 1) · `Broadcaster` (Task 2) · `classify` (Task 3)
- Produces for Task 6 (the proxy):
  - `POST /api/tool-calls` with body `{"server_name", "tool_name", "arguments", "annotations"}` returns either `{"policy": "allowed", "capability", "reason"}` or `{"policy": "approval_required", "approval": {"id", ..., "expires_at"}}`.
  - `GET /api/approvals/{id}` returns `{"id", "status", "expires_at"}`, where status is `pending`, `approved`, `denied` or `expired`.

- [ ] **Step 1: Write the failing tests.** Replace **all** of `apps/api/tests/test_policy.py` with:

```python
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.DATABASE_PATH", tmp_path / "test.db")
    monkeypatch.setenv("MCP_CONTROL_ALLOWED_CONFIG_ROOTS", str(tmp_path))
    with TestClient(app) as test_client:
        yield test_client


def call(client, tool_name, arguments=None, annotations=None):
    return client.post("/api/tool-calls", json={"server_name": "files", "tool_name": tool_name, "arguments": arguments or {}, "annotations": annotations or {}})


def test_read_call_is_allowed(client):
    response = call(client, "read_file", {"path": "notes.txt"}, {"readOnlyHint": True})
    assert response.status_code == 200
    assert response.json()["policy"] == "allowed"


def test_delete_call_requires_approval(client):
    response = call(client, "delete_file", {"path": "report.csv"})
    assert response.json()["policy"] == "approval_required"
    assert response.json()["approval"]["risk"] == "delete"


def test_human_decision_is_final(client):
    approval_id = call(client, "delete_file", {"path": "report.csv"}).json()["approval"]["id"]
    assert client.post(f"/api/approvals/{approval_id}", json={"decision": "denied"}).status_code == 200
    assert client.get(f"/api/approvals/{approval_id}").json()["status"] == "denied"
    assert client.post(f"/api/approvals/{approval_id}", json={"decision": "approved"}).status_code == 409


def test_unanswered_approval_expires(client, monkeypatch):
    monkeypatch.setenv("MCP_CONTROL_APPROVAL_TTL_SECONDS", "-1")
    approval_id = call(client, "delete_file", {"path": "report.csv"}).json()["approval"]["id"]
    assert client.get(f"/api/approvals/{approval_id}").json()["status"] == "expired"
    assert client.post(f"/api/approvals/{approval_id}", json={"decision": "approved"}).status_code == 409


def test_secrets_never_reach_the_database(client):
    call(client, "write_file", {"path": "a.txt", "api_key": "sk-supersecretvalue123"})
    dashboard = client.get("/api/dashboard").text
    assert "supersecretvalue" not in dashboard


def test_codex_config_import_is_read_only(client, tmp_path):
    config = tmp_path / "config.toml"
    original = '[mcp_servers.files]\ncommand = "npx"\nargs = ["server"]\nenv = { TOKEN = "not persisted" }\n'
    config.write_text(original)
    response = client.post("/api/imports", json={"source": "codex", "path": str(config)})
    assert response.status_code == 201
    assert response.json()["file_name"] == "config.toml"
    assert config.read_text() == original
    assert "not persisted" not in client.get("/api/dashboard").text
```

The `client` fixture gives each test a fresh, empty database in a temporary folder, so tests never touch your real data.

- [ ] **Step 2: Run them and watch them fail**

```powershell
py -m pytest apps/api/tests/test_policy.py -v
```
Expected: several FAIL (for example `422 Unprocessable Entity`, because the old API still wants a `capability` field).

- [ ] **Step 3: Replace all of `apps/api/app/main.py`** with:

```python
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.adapters import ConfigImportError, import_config
from app.events import Broadcaster
from app.policy import classify
from app.redaction import preview, redact, redact_text


DATABASE_URL = os.getenv("MCP_CONTROL_DATABASE_URL", "sqlite:///./data/mcp-control-room.db")
DATABASE_PATH = Path(DATABASE_URL.removeprefix("sqlite:///"))
broadcaster = Broadcaster(buffer_size=int(os.getenv("MCP_CONTROL_EVENT_BUFFER_SIZE", "500")))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def approval_ttl() -> timedelta:
    return timedelta(seconds=int(os.getenv("MCP_CONTROL_APPROVAL_TTL_SECONDS", "120")))


def db() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def add_missing_columns(connection: sqlite3.Connection, table: str, columns: tuple[tuple[str, str], ...]) -> None:
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns:
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def initialise_database() -> None:
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS connections (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                tool_count INTEGER NOT NULL DEFAULT 0,
                source_path TEXT,
                source_modified_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                server_name TEXT NOT NULL,
                action_summary TEXT NOT NULL,
                risk TEXT NOT NULL,
                rationale TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                decided_at TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        add_missing_columns(connection, "connections", (("source_path", "TEXT"), ("source_modified_at", "TEXT"), ("metadata_json", "TEXT NOT NULL DEFAULT '{}'")))
        add_missing_columns(connection, "approvals", (("tool_name", "TEXT"), ("arguments_preview", "TEXT"), ("expires_at", "TEXT")))


async def publish(event_type: str, payload: dict) -> None:
    broadcaster.publish({"id": str(uuid.uuid4()), "type": event_type, "at": now(), "data": redact(payload)})


def audit(event_type: str, summary: str) -> None:
    with db() as connection:
        connection.execute(
            "INSERT INTO audit_events (id, event_type, summary, created_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), event_type, redact_text(summary), now()),
        )


async def expire_stale_approvals() -> None:
    with db() as connection:
        stale = connection.execute("SELECT id, action_summary FROM approvals WHERE status = 'pending' AND expires_at < ?", (now(),)).fetchall()
        for row in stale:
            connection.execute("UPDATE approvals SET status = 'expired', decided_at = ? WHERE id = ?", (now(), row["id"]))
    for row in stale:
        audit("approval.expired", f"Expired without a decision: {row['action_summary']}")
        await publish("approval.expired", {"id": row["id"], "status": "expired"})


class ConnectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    source: Literal["codex", "claude", "manual"] = "manual"
    tool_count: int = Field(default=0, ge=0, le=10_000)


class ToolCallInput(BaseModel):
    server_name: str = Field(min_length=1, max_length=100)
    tool_name: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)


class ImportInput(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    source: Literal["codex", "claude"]


class DecisionInput(BaseModel):
    decision: Literal["approved", "denied"]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialise_database()
    yield


app = FastAPI(title="MCP Control Room", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "mcp-control-room"}


@app.get("/api/dashboard")
async def dashboard() -> dict:
    await expire_stale_approvals()
    with db() as connection:
        connections = [dict(row) for row in connection.execute("SELECT * FROM connections ORDER BY updated_at DESC")]
        approvals = [dict(row) for row in connection.execute("SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at DESC")]
        events = [dict(row) for row in connection.execute("SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 20")]
    return {"connections": connections, "pending_approvals": approvals, "events": events}


@app.post("/api/connections", status_code=201)
async def create_connection(payload: ConnectionInput) -> dict:
    connection_id = str(uuid.uuid4())
    timestamp = now()
    with db() as connection:
        connection.execute(
            "INSERT INTO connections (id, name, source, status, tool_count, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?, ?)",
            (connection_id, payload.name, payload.source, payload.tool_count, timestamp, timestamp),
        )
    result = {"id": connection_id, **payload.model_dump(), "status": "active", "created_at": timestamp, "updated_at": timestamp}
    audit("connection.created", f"Connected {payload.name} from {payload.source} configuration")
    await publish("connection.created", result)
    return result


@app.post("/api/imports", status_code=201)
async def import_connections(payload: ImportInput) -> dict:
    try:
        source_path, parsed = import_config(payload.path, payload.source)
    except (OSError, ConfigImportError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    modified_at = datetime.fromtimestamp(source_path.stat().st_mtime, timezone.utc).isoformat()
    timestamp = now()
    imported = []
    with db() as connection:
        for item in parsed:
            metadata = json.dumps({"transport": item.transport, "unknown_field_names": item.unknown_field_names})
            existing = connection.execute("SELECT id FROM connections WHERE name = ? AND source = ? AND source_path = ?", (item.name, payload.source, str(source_path))).fetchone()
            if existing:
                connection.execute("UPDATE connections SET status = ?, source_modified_at = ?, metadata_json = ?, updated_at = ? WHERE id = ?", ("active" if item.enabled else "inactive", modified_at, metadata, timestamp, existing["id"]))
                imported.append(existing["id"])
            else:
                connection_id = str(uuid.uuid4())
                connection.execute("INSERT INTO connections (id, name, source, status, tool_count, source_path, source_modified_at, metadata_json, created_at, updated_at) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?)", (connection_id, item.name, payload.source, "active" if item.enabled else "inactive", str(source_path), modified_at, metadata, timestamp, timestamp))
                imported.append(connection_id)
    audit("connection.imported", f"Imported {len(imported)} connection(s) from {source_path.name}")
    await publish("connection.imported", {"source": payload.source, "count": len(imported)})
    return {"source": payload.source, "file_name": source_path.name, "imported_connection_ids": imported}


@app.post("/api/tool-calls")
async def evaluate_tool_call(payload: ToolCallInput) -> dict:
    # Deterministic enforcement; server-provided text can raise risk but never lower it.
    decision = classify(payload.server_name, payload.tool_name, payload.arguments, payload.annotations)
    arguments_preview = preview(payload.arguments)
    summary = f"{payload.server_name}.{payload.tool_name} {arguments_preview}"
    if not decision.requires_approval:
        audit("tool_call.allowed", f"Allowed {summary}")
        await publish("tool_call.allowed", {"server_name": payload.server_name, "tool_name": payload.tool_name, "arguments_preview": arguments_preview, "capability": decision.capability})
        return {"policy": "allowed", "capability": decision.capability, "reason": decision.reason}

    approval_id = str(uuid.uuid4())
    created = datetime.now(timezone.utc)
    expires_at = (created + approval_ttl()).isoformat()
    with db() as connection:
        connection.execute(
            "INSERT INTO approvals (id, server_name, tool_name, action_summary, arguments_preview, risk, rationale, status, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (approval_id, payload.server_name, payload.tool_name, summary, arguments_preview, decision.capability, decision.reason, created.isoformat(), expires_at),
        )
    approval = {"id": approval_id, "server_name": payload.server_name, "tool_name": payload.tool_name, "action_summary": summary, "arguments_preview": arguments_preview, "risk": decision.capability, "rationale": decision.reason, "status": "pending", "created_at": created.isoformat(), "expires_at": expires_at}
    audit("approval.requested", f"Approval required: {summary}")
    await publish("approval.requested", approval)
    return {"policy": "approval_required", "approval": approval}


@app.get("/api/approvals/{approval_id}")
async def get_approval(approval_id: str) -> dict:
    await expire_stale_approvals()
    with db() as connection:
        row = connection.execute("SELECT id, status, expires_at FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return dict(row)


@app.post("/api/approvals/{approval_id}")
async def decide_approval(approval_id: str, payload: DecisionInput) -> dict:
    await expire_stale_approvals()
    with db() as connection:
        existing = connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        if existing["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"Approval is already {existing['status']}")
        connection.execute("UPDATE approvals SET status = ?, decided_at = ? WHERE id = ?", (payload.decision, now(), approval_id))
    audit(f"approval.{payload.decision}", f"{payload.decision.capitalize()} {existing['action_summary']}")
    result = {"id": approval_id, "status": payload.decision}
    await publish(f"approval.{payload.decision}", result)
    return result


@app.get("/api/events")
async def events(request: Request) -> StreamingResponse:
    queue = broadcaster.subscribe(request.headers.get("last-event-id"))

    async def stream() -> AsyncIterator[str]:
        try:
            yield "retry: 3000\n\n"
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
```

What changed, in plain English:
- `publish()` masks the payload, then hands it to the broadcaster.
- `audit()` masks the summary text before saving.
- `expire_stale_approvals()` runs before anyone reads or decides approvals. It flips old `pending` requests to `expired` and logs that.
- `evaluate_tool_call()` calls `classify`. It never trusts the caller about risk.

- [ ] **Step 4: Run the whole test suite**

```powershell
py -m pytest
```
Expected: `21 passed` (4 redaction + 3 events + 6 rules + 2 adapters + 6 API).

- [ ] **Step 5: Try it by hand**

```powershell
py -m uvicorn app.main:app --app-dir apps/api --reload
```
Open http://127.0.0.1:8000/docs. This is FastAPI's built-in test page. Open `POST /api/tool-calls`, click **Try it out** and send:
```json
{"server_name": "files", "tool_name": "delete_file", "arguments": {"path": "a.txt", "token": "abc"}}
```
Expected: `"policy": "approval_required"`, and `arguments_preview` shows `"token": "[REDACTED]"`. Stop the server with `Ctrl+C`.

- [ ] **Step 6: Commit**

```powershell
git add apps/api/app/main.py apps/api/tests/test_policy.py
git commit -m "feat(api): server-side classification, approval expiry and status polling"
```

---

### Task 6: The MCP proxy — the heart of the project

**Why:** Without this, the project is only a dashboard. The proxy is what makes it **real**. Your AI assistant starts the proxy *instead of* the MCP server, and the proxy starts the real server itself. Then it copies messages back and forth line by line:
- **Most messages** pass straight through untouched.
- **`tools/list` replies** coming back from the server: the proxy remembers each tool's hints to send along later. They're treated as untrusted.
- **`tools/call` requests** coming from the AI: the proxy asks the API. If the call is allowed, it forwards it. If approval is needed, it checks the API every second until you decide. If you deny it, the request expires, or the API is down, the proxy **never sends it to the server**. Instead it replies to the AI with "Blocked by MCP Control Room: …".
- While a call waits for you, it waits on its own **thread**, so other messages keep flowing and the AI doesn't freeze.

It uses only the Python standard library, so there's nothing extra to install.

**Files:**
- Create: `apps/proxy/control_room_proxy.py`
- Create: `apps/proxy/tests/fake_server.py` (a pretend MCP server with one read tool and one delete tool, used by tests)
- Test: `apps/proxy/tests/test_proxy.py`

**Interfaces:**
- Consumes: `POST /api/tool-calls` and `GET /api/approvals/{id}` from Task 5.
- Produces: the command `python apps/proxy/control_room_proxy.py --name <server-name> [--api URL] [--timeout SECONDS] -- <real server command...>`.

- [ ] **Step 1: Create the fake server** `apps/proxy/tests/fake_server.py`:

```python
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
```

- [ ] **Step 2: Write the failing tests.** Create `apps/proxy/tests/test_proxy.py`:

```python
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
```

The last test is a real end-to-end run. It starts the proxy with the fake server, points it at an address where nothing is listening, and checks two things: `tools/list` still works, and the tool call is **blocked**. That's "fail closed", proven.

- [ ] **Step 3: Run them and watch them fail**

```powershell
py -m pytest apps/proxy -v
```
Expected: FAIL with `No module named 'control_room_proxy'`.

- [ ] **Step 4: Write the proxy.** Create `apps/proxy/control_room_proxy.py`:

```python
"""Stdio MCP proxy.

Sits between an MCP client (Claude Desktop, Claude Code, Codex) and a real MCP server.
Every message passes straight through, except `tools/call`: before forwarding one,
the proxy asks the Control Room API and waits for a human decision when required.
If the API cannot be reached, the call is blocked (fail closed).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Any, Callable


CheckFunction = Callable[[str, str, dict, dict], "tuple[bool, str]"]


class PolicyClient:
    def __init__(self, base_url: str, timeout_seconds: float = 130.0, poll_seconds: float = 1.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
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
        self._lock = threading.Lock()

    def from_client(self, message: dict) -> tuple[str, dict]:
        """Return ("forward", message) to send it to the server, or ("reply", response) to answer the client directly."""
        if message.get("method") == "tools/list" and "id" in message:
            with self._lock:
                self._tools_list_ids.add(message["id"])
        if message.get("method") != "tools/call":
            return "forward", message

        params = message.get("params") or {}
        tool_name = str(params.get("name", ""))
        arguments = params.get("arguments") or {}
        with self._lock:
            annotations = self.annotations.get(tool_name, {})
        allowed, reason = self.check(self.server_name, tool_name, arguments, annotations)
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
    parser.add_argument("--timeout", type=float, default=130.0, help="Seconds to wait for a human decision.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="The real MCP server command, after --")
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("put the real MCP server command after --")

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
        (send_to_server if action == "forward" else send_to_client)(outgoing)

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
```

- [ ] **Step 5: Run all tests**

```powershell
py -m pytest
```
Expected: `25 passed`. The last proxy test takes a few seconds.

- [ ] **Step 6: Commit**

```powershell
git add apps/proxy
git commit -m "feat(proxy): stdio MCP proxy that gates tools/call on human approval"
```

---

### Task 7: Try it with a real AI assistant (manual test)

**Why:** Tests prove the pieces work. This proves the **whole product** works, and it's the demo you'll record. You'll put the proxy in front of the official **filesystem MCP server**, limited to a sandbox folder you don't care about.

- [ ] **Step 1: Make a sandbox folder with a throwaway file**

```powershell
New-Item -ItemType Directory -Force C:\Users\sonim\mcp-sandbox
Set-Content C:\Users\sonim\mcp-sandbox\hello.txt "hello from the sandbox"
```

- [ ] **Step 2: Start the API** (terminal 1, with the venv active)

```powershell
py -m uvicorn app.main:app --app-dir apps/api --reload
```

- [ ] **Step 3: Start the dashboard** (terminal 2)

```powershell
Set-Location apps/web
npm.cmd run dev
```
Open http://localhost:5173. You should see **● Live** in the top right.

- [ ] **Step 4: Register the guarded server with Claude Code** (terminal 3). This is all one command:

```powershell
claude mcp add files-guarded -- C:\Users\sonim\mcp_control_rom\.venv\Scripts\python.exe C:\Users\sonim\mcp_control_rom\apps\proxy\control_room_proxy.py --name files -- npx.cmd -y @modelcontextprotocol/server-filesystem C:\Users\sonim\mcp-sandbox
```
Everything after the first `--` is the command Claude Code will run (your proxy). Everything after the second `--` is the real server the proxy starts.

*Using Claude Desktop instead?* Open `%APPDATA%\Claude\claude_desktop_config.json` and add:
```json
{
  "mcpServers": {
    "files-guarded": {
      "command": "C:\\Users\\sonim\\mcp_control_rom\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\sonim\\mcp_control_rom\\apps\\proxy\\control_room_proxy.py", "--name", "files", "--",
               "npx.cmd", "-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\sonim\\mcp-sandbox"]
    }
  }
}
```
Then fully quit and reopen Claude Desktop.

- [ ] **Step 5: Test the three cases.** Start `claude` in a new terminal and ask:
  1. *"Use files-guarded to read hello.txt in the sandbox."* The read should go straight through. The audit trail shows `tool_call.allowed`.
     - If it lands in the approval queue instead, this version of the filesystem server doesn't mark `read_text_file` as read-only. That's the rules staying safe, not a bug. Mark it trusted yourself: stop the API, run `$env:MCP_CONTROL_TRUSTED_READ_TOOLS = "files:read_text_file,files:list_directory"` in terminal 1, and start the API again.
  2. *"Use files-guarded to write a file called notes.txt saying hi."* The request appears in the **Approval queue** with a countdown. Click **Approve**. The AI reports success and `notes.txt` now exists.
  3. Ask it to write another file, then click **Deny**. The AI is told "Blocked by MCP Control Room: The call was denied…" and the file is **not** created.

  Claude Code may show its own permission prompt as well. That's separate from yours. Allow it, so the call reaches your proxy.

- [ ] **Step 6: Test fail-closed.** Stop the API (`Ctrl+C` in terminal 1) and ask for another write. The AI should be told the call was blocked because Control Room is unreachable. Start the API again afterwards.

- [ ] **Step 7: Nothing to commit** (you didn't change any code). Write down anything odd you noticed. It's good interview material ("I found that…").

---

### Task 8: Update the dashboard

**Why:** The dashboard needs to show the new information: which tool, the (masked) arguments and a countdown until expiry. It also needs to react to the new `tool_call.allowed` and `approval.expired` events. The old "Judge & cost analyst" box was a placeholder for a feature that doesn't exist; it's replaced by an honest "How decisions are made" box. You'll also pin package versions, because `"latest"` means your project could break any day without you changing anything.

**Files:**
- Replace: `apps/web/src/main.tsx`
- Modify: `apps/web/src/styles.css` (add one line)
- Replace: `apps/web/package.json`
- Modify: `packages/contracts/events.schema.json`

- [ ] **Step 1: Replace all of `apps/web/src/main.tsx`** with:

```tsx
import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type Connection = { id: string; name: string; source: string; status: string; tool_count: number };
type Approval = { id: string; server_name: string; tool_name: string | null; action_summary: string; arguments_preview: string | null; risk: string; rationale: string; status: string; expires_at: string | null };
type Audit = { id: string; event_type: string; summary: string; created_at: string };
type Dashboard = { connections: Connection[]; pending_approvals: Approval[]; events: Audit[] };

const api = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const liveEvents = ["connection.created", "connection.imported", "tool_call.allowed", "approval.requested", "approval.approved", "approval.denied", "approval.expired"];

function App() {
  const [data, setData] = useState<Dashboard>({ connections: [], pending_approvals: [], events: [] });
  const [streamState, setStreamState] = useState("Connecting");
  const [message, setMessage] = useState("");
  const [clock, setClock] = useState(Date.now());

  const load = useCallback(async () => {
    const response = await fetch(`${api}/api/dashboard`);
    if (!response.ok) throw new Error("Dashboard unavailable");
    setData(await response.json());
  }, []);

  useEffect(() => {
    load().catch(() => setMessage("Start the API to see live data."));
    const source = new EventSource(`${api}/api/events`);
    source.onopen = () => setStreamState("Live");
    source.onerror = () => setStreamState("Reconnecting");
    liveEvents.forEach((name) => source.addEventListener(name, () => load().catch(() => undefined)));
    return () => source.close();
  }, [load]);

  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  async function decide(id: string, decision: "approved" | "denied") {
    const response = await fetch(`${api}/api/approvals/${id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision }) });
    if (!response.ok) setMessage("That decision could not be saved. It may have expired.");
    else { setMessage(`Action ${decision}.`); }
    await load();
  }

  function secondsLeft(expiresAt: string | null) {
    return expiresAt ? Math.max(0, Math.round((Date.parse(expiresAt) - clock) / 1000)) : null;
  }

  return <main>
    <header><div><p className="eyebrow">LOCAL-FIRST MCP GOVERNANCE</p><h1>Control Room</h1></div><span className={`live ${streamState === "Live" ? "connected" : ""}`}>● {streamState}</span></header>
    {message && <p className="notice" aria-live="polite">{message}</p>}
    <section className="metrics" aria-label="Overview">
      <Metric label="Connected servers" value={data.connections.filter(c => c.status === "active").length} detail="Selected local configurations" />
      <Metric label="Pending approvals" value={data.pending_approvals.length} detail="Nothing risky runs without you" warn={data.pending_approvals.length > 0} />
      <Metric label="Audit entries" value={data.events.length} detail="Redacted event history" />
    </section>
    <section className="grid">
      <article className="panel approvals" aria-live="polite"><div className="panel-title"><div><p className="eyebrow">HUMAN IN THE LOOP</p><h2>Approval queue</h2></div><span>{data.pending_approvals.length}</span></div>
        {data.pending_approvals.length === 0 ? <Empty text="No actions are waiting for a decision." /> : data.pending_approvals.map(item => <div className="approval" key={item.id}>
          <div>
            <span className="risk">{item.risk}</span>
            <h3>{item.server_name} · {item.tool_name ?? item.action_summary}</h3>
            {item.arguments_preview && <code className="args">{item.arguments_preview}</code>}
            <p>{item.rationale}{secondsLeft(item.expires_at) !== null && ` · expires in ${secondsLeft(item.expires_at)}s`}</p>
          </div>
          <div className="actions"><button className="deny" onClick={() => decide(item.id, "denied")}>Deny</button><button className="approve" onClick={() => decide(item.id, "approved")}>Approve</button></div>
        </div>)}
      </article>
      <article className="panel"><p className="eyebrow">POLICY</p><h2>How decisions are made</h2><div className="advice">
        <p>Delete, credential, execute, network and write calls always wait for you. A call runs straight away only when its name reads like a read <em>and</em> the server marks it read-only, or you listed it in <code>MCP_CONTROL_TRUSTED_READ_TOOLS</code>.</p>
        <small>Rules are plain code. Server text can raise risk but never lower it. Unanswered requests expire and are blocked.</small>
      </div></article>
    </section>
    <section className="grid lower">
      <article className="panel"><p className="eyebrow">INVENTORY</p><h2>Connections</h2>{data.connections.length === 0 ? <Empty text="No configurations have been imported." /> : data.connections.map(c => <div className="row" key={c.id}><div><strong>{c.name}</strong><p>{c.source}</p></div><span className="status">{c.status}</span></div>)}</article>
      <article className="panel"><p className="eyebrow">SANITIZED ACTIVITY</p><h2>Audit trail</h2>{data.events.length === 0 ? <Empty text="Events will appear here after a policy decision." /> : data.events.map(e => <div className="row audit" key={e.id}><div><strong>{e.summary}</strong><p>{new Date(e.created_at).toLocaleString()}</p></div><code>{e.event_type}</code></div>)}</article>
    </section>
  </main>;
}

function Metric({ label, value, detail, warn = false }: { label: string; value: number; detail: string; warn?: boolean }) { return <article className={`metric ${warn ? "warn" : ""}`}><p>{label}</p><strong>{value}</strong><small>{detail}</small></article>; }
function Empty({ text }: { text: string }) { return <p className="empty">{text}</p>; }

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
```

- [ ] **Step 2: Add this line to the end of `apps/web/src/styles.css`:**

```css
.args { display: block; margin: 4px 0 6px; color: #c9d6ef; font-size: .78rem; word-break: break-all; }
```

- [ ] **Step 3: Replace all of `apps/web/package.json`** with these pinned versions (they're the ones you already have installed):

```json
{
  "name": "mcp-control-room-web",
  "private": true,
  "version": "0.2.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build"
  },
  "dependencies": {
    "@vitejs/plugin-react": "6.1.1",
    "react": "19.3.0",
    "react-dom": "19.3.0",
    "vite": "8.3.0"
  },
  "devDependencies": {
    "@types/react": "19.3.0",
    "@types/react-dom": "19.3.0",
    "typescript": "7.0.2"
  }
}
```
(The old `lint` script was removed because ESLint was never installed.)

- [ ] **Step 4: Update the lock file and check that it builds**

```powershell
Set-Location apps/web
npm.cmd install
npm.cmd run build
Set-Location ../..
```
Expected: the build ends with `✓ built in …`. If TypeScript prints errors, re-copy `main.tsx` exactly.

- [ ] **Step 5: Add the new event names to `packages/contracts/events.schema.json`.** Change the `"enum"` line to:

```json
      "enum": ["connection.created", "connection.imported", "tool_call.allowed", "approval.requested", "approval.approved", "approval.denied", "approval.expired"]
```

- [ ] **Step 6: Check it by eye.** Run the API and `npm.cmd run dev`, then repeat Task 7 Step 5 (case 2). The approval card should show the tool name, the arguments and a countdown. Open a **second** browser tab too: both should update live (that's Task 2 working).

- [ ] **Step 7: Commit**

```powershell
git add apps/web packages/contracts
git commit -m "feat(web): show tool, masked arguments and expiry; pin dependencies"
```

---

### Task 9: Settings, docs, CI and demo

**Why:** Recruiters spend about 30 seconds on a repo. A clear README, a green CI badge and a GIF of the product working matter more than any single feature.

**Files:**
- Replace: `.env.example`
- Modify: `README.md`
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Replace `.env.example`** with:

```dotenv
# Public UI endpoint only; no secrets belong here.
VITE_API_BASE_URL=http://localhost:8000

# API runtime
MCP_CONTROL_DATABASE_URL=sqlite:///./data/mcp-control-room.db
# Folders config imports may read from, separated by ; on Windows (: on Mac/Linux). Empty = your home folder.
MCP_CONTROL_ALLOWED_CONFIG_ROOTS=
MCP_CONTROL_REDACTION_KEYS=api_key,apikey,authorization,password,secret,token
MCP_CONTROL_EVENT_BUFFER_SIZE=500
# Seconds before an unanswered approval expires and the call is blocked.
MCP_CONTROL_APPROVAL_TTL_SECONDS=120
# server:tool pairs you trust as read-only, comma separated. Example: files:read_text_file,files:list_directory
MCP_CONTROL_TRUSTED_READ_TOOLS=
```
Then run `Copy-Item .env.example .env` (if you haven't already), and from now on start the API with `--env-file .env`, so these settings are actually loaded:
```powershell
py -m uvicorn app.main:app --app-dir apps/api --reload --env-file .env
```

- [ ] **Step 2: Create `.github/workflows/ci.yml`**

```yaml
name: CI
on: [push, pull_request]

jobs:
  api-and-proxy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r apps/api/requirements-dev.txt
      - run: pytest

  web:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: apps/web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - run: npm ci
      - run: npm run build
```

- [ ] **Step 3: Update `README.md`.** Keep the existing content and make three changes:
  1. Under the title, add a one-line pitch: *"A human-in-the-loop security gateway for AI agents: risky MCP tool calls pause until you approve them."*
  2. Add a **"How it works"** section with the picture from the top of this plan, plus a **"Try it"** section with Task 7 Steps 2–5.
  3. Change the test command in "Local development setup" to plain `py -m pytest` (run from the project root), and the API command to include `--env-file .env`.

- [ ] **Step 4: Record a demo GIF** (about 30 seconds) of Task 7 Step 5 case 2. Show the AI asking to write, the card appearing with a countdown, you clicking Deny, and the AI reporting it was blocked. On Windows you can use **ShareX** (free) → Screen recording (GIF). Save it as `docs/demo.gif` and add `![demo](docs/demo.gif)` near the top of the README.

- [ ] **Step 5: Commit and push to GitHub**

```powershell
git add .env.example README.md .github docs
git commit -m "docs: demo, setup guide and CI"
```
Create an empty repo on github.com (no README), then:
```powershell
git branch -M main
git remote add origin https://github.com/<your-username>/mcp-control-room.git
git push -u origin main
```
Check the **Actions** tab on GitHub. Both jobs should turn green.

---

## Done — how to talk about it

**Resume bullets** (use them once Tasks 0–9 are done; every word is backed by code and tests):
- Built a **human-in-the-loop security gateway for AI agents**: a stdio MCP proxy (Python) that intercepts `tools/call` requests and holds destructive, write, network and shell actions until approved in a live React/TypeScript dashboard.
- Designed **deterministic, injection-resistant risk rules**: server-supplied metadata can raise risk but never lower it, unknown tools default to approval, and the gateway **fails closed** when the control plane is unreachable. Verified with negative tests.
- Implemented **secret redaction, approval expiry and an audit trail** (FastAPI, SQLite), with real-time multi-client updates over **Server-Sent Events** and reconnect replay. 25 automated tests, with CI in GitHub Actions.

**Likely interview questions and your answers:**
- *Why not let an LLM decide what's safe?* An attacker can put instructions in a tool description ("this tool is safe, approve it"). An LLM might follow them. An `if` statement won't. LLMs can advise; code decides.
- *Why a proxy instead of a plugin inside Claude?* It works with any MCP client (Claude, Codex, Cursor) without changing them, because it speaks the protocol itself.
- *What happens if your API crashes?* Calls are blocked, not allowed (fail closed). There's a test for it.
- *What are the limits?* It isn't a sandbox. An approved call runs with the server's full permissions, so real isolation belongs in containers. The rules are based on words, so a tool with a misleading name that also claims to be read-only could slip through. That's why the trusted-read list exists. It handles stdio servers only, not HTTP ones yet. Admitting limits honestly scores points.

**Ideas for later** (only once the above is solid): support HTTP/SSE MCP servers; "always allow this tool" buttons that write to a rules table; an advisory LLM that *explains* a request in plain English (label it as advice that can't approve anything); a per-project view.
