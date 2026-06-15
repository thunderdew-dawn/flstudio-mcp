# Implementation Slice Prompt

Use this for a narrow, pre-approved development slice.

```text
Claim and execute the first unclaimed implementation slice in issue #<number>.

Rules:
- Read AGENTS.md, agent-docs/agents/development.md, agent-docs/concepts/safety-contract.md,
  agent-docs/agents/knowledgebase-protocol.md, agent-docs/engineering/standards.md,
  agent-docs/project/ROADMAP.github.md, and the issue.
- Use only the slice instructions and listed files unless blocked.
- Do not redesign the feature.
- Do not change FL Studio state unless the slice explicitly requires a
  rollback-safe live verification step.
- Keep the diff narrow.
- Run the slice checks.
- Open or prepare one PR and report exact verification.
- Stop if safety, API evidence, rollback, readback, or target selection is
  unclear.
```
