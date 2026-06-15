# Bug Triage Prompt

Use this to classify and prepare a bug before implementation.

```text
Triage GitHub bug issue #<number>.

Tasks:
- Read AGENTS.md, agent-docs/agents/github-playbook.md,
  agent-docs/concepts/safety-contract.md, agent-docs/engineering/standards.md,
  agent-docs/project/ROADMAP.github.md, and the issue.
- Classify as reproducible, needs-info, duplicate, expected API limitation, or
  real defect.
- Identify the smallest affected surface.
- List exact files/tests to inspect.
- State whether live FL verification is required.
- If live verification is required, propose read-only first, then rollback-safe
  probe steps.
- Do not implement yet unless the fix is obvious and isolated.
```
