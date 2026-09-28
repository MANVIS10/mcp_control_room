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


def sensitive_keys() -> set[str]:
    raw = os.getenv("MCP_CONTROL_REDACTION_KEYS") or DEFAULT_KEYS
    return {key.strip().lower() for key in raw.split(",") if key.strip()}


def redact_text(text: str) -> str:
    for pattern in TOKEN_PATTERNS:
        text = pattern.sub(MASK, text)
    return text


def redact(value: Any, keys: set[str] | None = None) -> Any:
    keys = sensitive_keys() if keys is None else keys
    if isinstance(value, dict):
        return {k: MASK if any(s in str(k).lower() for s in keys) else redact(v, keys) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, keys) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def preview(arguments: dict) -> str:
    text = json.dumps(redact(arguments), ensure_ascii=False, default=str)
    return text if len(text) <= MAX_PREVIEW_CHARS else text[: MAX_PREVIEW_CHARS - 1] + "…"
