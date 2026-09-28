"""Read-only, secret-safe configuration importers."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


Source = Literal["codex", "claude"]
MAX_CONFIG_BYTES = 1_000_000


class ConfigImportError(ValueError):
    pass


@dataclass(frozen=True)
class ImportedConnection:
    name: str
    enabled: bool
    transport: Literal["stdio", "http", "unknown"]
    unknown_field_names: list[str]


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
    if not path.is_file():
        raise ConfigImportError("The selected configuration path is not a file.")
    if path.stat().st_size > MAX_CONFIG_BYTES:
        raise ConfigImportError("Configuration files larger than 1 MB are not imported.")

    try:
        raw = path.read_bytes()
        document = tomllib.loads(raw.decode("utf-8")) if source == "codex" else json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, json.JSONDecodeError) as error:
        raise ConfigImportError("The selected file is not valid for the chosen source.") from error

    servers = document.get("mcp_servers", {}) if source == "codex" else document.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ConfigImportError("No MCP server mapping was found in the selected file.")

    imported: list[ImportedConnection] = []
    for name, config in servers.items():
        if not isinstance(name, str) or not isinstance(config, dict):
            continue
        transport: Literal["stdio", "http", "unknown"]
        if isinstance(config.get("command"), str):
            transport = "stdio"
        elif isinstance(config.get("url"), str):
            transport = "http"
        else:
            transport = "unknown"
        known = {"command", "args", "env", "env_vars", "cwd", "url", "headers", "http_headers", "bearer_token_env_var", "enabled", "enabled_tools", "disabled_tools", "startup_timeout_sec", "tool_timeout_sec", "oauth"}
        imported.append(ImportedConnection(name=name, enabled=config.get("enabled", True) is not False, transport=transport, unknown_field_names=sorted(str(key) for key in config if key not in known)))
    return path, imported
