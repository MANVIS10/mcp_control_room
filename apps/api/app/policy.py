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
