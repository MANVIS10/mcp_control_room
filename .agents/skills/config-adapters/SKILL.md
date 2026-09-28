---
name: config-adapters
description: Build read-only adapters that import and normalize Codex or Claude MCP connection configurations.
---

# Configuration Adapter Work

- Do not assume config paths or schemas. Require a user-selected path or a documented, opt-in discovery root.
- Parse defensively, preserve unknown fields separately, validate a normalized schema, and report diagnostics without logging secrets.
- Importing is idempotent and read-only. Do not launch a server, change an existing config, or resolve environment variables as part of discovery.
- Store source provenance and modification time so the UI can explain where each connection came from.
- Add fixtures for valid, malformed, secret-bearing, and schema-variant inputs.
