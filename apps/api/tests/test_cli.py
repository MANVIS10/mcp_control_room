import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import cli
from app.main import app


def test_config_prints_json_a_client_can_paste(tmp_path, capsys):
    assert cli.main(["config", "--dir", str(tmp_path)]) == 0
    entry = json.loads(capsys.readouterr().out)["mcpServers"]["files-guarded"]
    assert entry["command"] == sys.executable
    assert entry["args"][:4] == ["-m", "control_room_proxy", "--name", "files"]
    assert entry["args"][-1] == str(tmp_path)
    assert "--" in entry["args"]


def test_config_creates_the_sandbox_folder_only_if_missing(tmp_path, capsys):
    target = tmp_path / "sandbox"
    cli.main(["config", "--dir", str(target)])
    assert target.is_dir()


def test_config_refuses_a_port_that_is_not_a_number(capsys):
    with pytest.raises(SystemExit):
        cli.main(["config", "--port", "abc"])


def test_dashboard_url_carries_the_token_in_the_fragment_only():
    url = cli.dashboard_url(8000, "secret-token-value-123")
    assert url == "http://127.0.0.1:8000/#token=secret-token-value-123"
    assert "?" not in url


def test_serve_binds_to_loopback_and_hands_the_token_to_the_api(monkeypatch, tmp_path, capsys):
    seen = {}
    monkeypatch.setattr("uvicorn.run", lambda application, **kw: seen.update(kw))
    for name in ("MCP_CONTROL_APPROVER_TOKEN", "MCP_CONTROL_DATABASE_URL"):
        monkeypatch.setenv(name, "placeholder")  # registers cleanup, since serve() writes os.environ directly
        monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert cli.main(["--port", "8765"]) == 0
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8765
    out = capsys.readouterr().out
    import os
    token = os.environ["MCP_CONTROL_APPROVER_TOKEN"]
    assert len(token) >= 16 and f"#token={token}" in out
    assert tmp_path.as_posix() in os.environ["MCP_CONTROL_DATABASE_URL"]


def test_dashboard_is_served_from_the_api_when_built(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.DATABASE_PATH", tmp_path / "t.db")
    monkeypatch.setenv("MCP_CONTROL_APPROVER_TOKEN", "test-approver-token-0123456789")
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200 and "MCP Control Room" in page.text
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/api/dashboard").status_code == 200
