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


def test_approvals_from_before_the_upgrade_expire(client):
    import app.main
    with app.main.db() as connection:
        connection.execute("INSERT INTO approvals (id, server_name, action_summary, risk, rationale, status, created_at) VALUES ('old', 'files', 'old request', 'delete', 'legacy', 'pending', '2020-01-01T00:00:00+00:00')")
    assert client.get("/api/approvals/old").json()["status"] == "expired"


def test_requests_for_other_hosts_are_rejected(client):
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/health", headers={"Host": "localhost:8000"}).status_code == 200
