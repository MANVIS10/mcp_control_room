from fastapi.testclient import TestClient

from app.main import app


def test_read_call_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.DATABASE_PATH", tmp_path / "test.db")
    with TestClient(app) as client:
        response = client.post("/api/tool-calls", json={"server_name": "files", "action_summary": "List project files", "capability": "read"})
    assert response.status_code == 200
    assert response.json()["policy"] == "allowed"


def test_delete_call_requires_approval(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.DATABASE_PATH", tmp_path / "test.db")
    with TestClient(app) as client:
        response = client.post("/api/tool-calls", json={"server_name": "files", "action_summary": "Delete report.csv", "capability": "delete"})
    assert response.status_code == 200
    assert response.json()["policy"] == "approval_required"


def test_codex_config_import_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.DATABASE_PATH", tmp_path / "test.db")
    config = tmp_path / "config.toml"
    original = '[mcp_servers.files]\ncommand = "npx"\nargs = ["server"]\nenv = { TOKEN = "not persisted" }\n'
    config.write_text(original)
    with TestClient(app) as client:
        response = client.post("/api/imports", json={"source": "codex", "path": str(config)})
    assert response.status_code == 201
    assert response.json()["file_name"] == "config.toml"
    assert config.read_text() == original
