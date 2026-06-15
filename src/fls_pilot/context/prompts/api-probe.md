# API Probe Prompt

Use this when behavior depends on FL Studio version, controller marker, target
selection, indexing, readback timing, or undocumented API behavior.

```text
Plan API/compatibility probe for issue #<number>.

Rules:
- Read AGENTS.md, agent-docs/concepts/safety-contract.md,
  agent-docs/agents/knowledgebase-protocol.md, agent-docs/agents/runtime-usage.md, and the
  issue.
- Check Knowledgebase first.
- Do not guess ranges, indices, IDs, or target selection.
- Prefer read-only evidence first.
- If a write is required, define snapshot, smallest write, readback, changelog,
  and rollback before execution.
- Store reusable findings in Knowledgebase and agent-docs/concepts/api-capability-audit.md when
  confirmed.
```
