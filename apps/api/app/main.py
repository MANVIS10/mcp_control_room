from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.adapters import ConfigImportError, import_config


DATABASE_URL = os.getenv("MCP_CONTROL_DATABASE_URL", "sqlite:///./data/mcp-control-room.db")
DATABASE_PATH = Path(DATABASE_URL.removeprefix("sqlite:///"))
event_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=int(os.getenv("MCP_CONTROL_EVENT_BUFFER_SIZE", "500")))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


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
        columns = {row[1] for row in connection.execute("PRAGMA table_info(connections)")}
        for name, definition in (("source_path", "TEXT"), ("source_modified_at", "TEXT"), ("metadata_json", "TEXT NOT NULL DEFAULT '{}'") ):
            if name not in columns:
                connection.execute(f"ALTER TABLE connections ADD COLUMN {name} {definition}")


async def publish(event_type: str, payload: dict) -> None:
    event = {"id": str(uuid.uuid4()), "type": event_type, "at": now(), "data": payload}
    if event_queue.full():
        event_queue.get_nowait()
    event_queue.put_nowait(event)


def audit(event_type: str, summary: str) -> None:
    with db() as connection:
        connection.execute(
            "INSERT INTO audit_events (id, event_type, summary, created_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), event_type, summary, now()),
        )


class ConnectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    source: Literal["codex", "claude", "manual"] = "manual"
    tool_count: int = Field(default=0, ge=0, le=10_000)


class ToolCallInput(BaseModel):
    server_name: str = Field(min_length=1, max_length=100)
    action_summary: str = Field(min_length=1, max_length=300)
    capability: Literal["read", "write", "execute", "network", "credential", "delete"]


class ImportInput(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    source: Literal["codex", "claude"]


class DecisionInput(BaseModel):
    decision: Literal["approved", "denied"]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialise_database()
    yield


app = FastAPI(title="MCP Control Room", version="0.1.0", lifespan=lifespan)
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
def dashboard() -> dict:
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
    # Deterministic enforcement; server-provided text never changes this decision.
    requires_approval = payload.capability in {"write", "execute", "network", "credential", "delete"}
    if not requires_approval:
        audit("tool_call.allowed", f"Allowed read call: {payload.action_summary}")
        await publish("tool_call.allowed", payload.model_dump())
        return {"policy": "allowed", "reason": "Read-only capability"}

    approval_id = str(uuid.uuid4())
    timestamp = now()
    rationale = f"{payload.capability.capitalize()} capabilities require a human decision."
    with db() as connection:
        connection.execute(
            "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL)",
            (approval_id, payload.server_name, payload.action_summary, payload.capability, rationale, timestamp),
        )
    approval = {"id": approval_id, **payload.model_dump(), "risk": payload.capability, "rationale": rationale, "status": "pending", "created_at": timestamp}
    audit("approval.requested", f"Approval required: {payload.action_summary}")
    await publish("approval.requested", approval)
    return {"policy": "approval_required", "approval": approval}


@app.post("/api/approvals/{approval_id}")
async def decide_approval(approval_id: str, payload: DecisionInput) -> dict:
    with db() as connection:
        existing = connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Approval not found")
        if existing["status"] != "pending":
            raise HTTPException(status_code=409, detail="Approval was already decided")
        connection.execute("UPDATE approvals SET status = ?, decided_at = ? WHERE id = ?", (payload.decision, now(), approval_id))
    audit(f"approval.{payload.decision}", f"{payload.decision.capitalize()} {existing['action_summary']}")
    result = {"id": approval_id, "status": payload.decision}
    await publish(f"approval.{payload.decision}", result)
    return result


@app.get("/api/events")
async def events() -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        yield "retry: 3000\n\n"
        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=15)
                yield f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
