---
name: advisory-agents
description: Implement the judge, recommender, learner, EOD, or cost advisory workflows for MCP Control Room.
---

# Advisory Agent Work

These workflows inform people; they do not silently alter configuration, grant approval, or execute tool calls.

- Start with deterministic evidence: active project files, declared dependencies, recent redacted events, user feedback, and configured budgets.
- Make every recommendation explainable: evidence, confidence, expected benefit, expected cost, and an action the person may accept or reject.
- Treat model cost estimates as estimates. Record provider/model, token counts if available, assumptions, and currency/date basis.
- Learning uses an explicit accept/reject/dismiss signal and must offer reset plus export. Do not infer sensitive preferences from raw prompts or tool arguments.
- LangGraph is justified only when its stateful, multi-step orchestration materially improves the workflow; otherwise keep the workflow as ordinary service functions.
