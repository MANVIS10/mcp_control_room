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
