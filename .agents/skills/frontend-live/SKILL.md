---
name: frontend-live
description: Build or modify the React TypeScript dashboard and its SSE-based live views for MCP Control Room.
---

# Live Frontend Work

- Treat SSE payloads as a versioned, sanitized read model from `packages/contracts`; never expose raw tool arguments or secrets.
- Reconnect with backoff and show connection state. Event IDs must allow recovery after a brief disconnect.
- Approval interactions must show the affected server, action summary, risk rationale, expiry, and explicit approve/deny choices. Never preselect approval.
- Accessibility is required for real-time changes: keyboard-operable controls, labels, focus handling for new approval requests, and non-disruptive live-region updates.
- Keep state-changing calls behind API commands. The dashboard never directly invokes an MCP server.
