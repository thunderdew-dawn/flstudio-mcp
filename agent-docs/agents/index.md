# Agents

**Create more. Check less.**

This section gives agents the smallest useful context for the task at hand.
Do not load every agent document by default. Choose the role first.

## Role Paths

### Use FLStudioPilot With FL Studio

For user-facing runtime workflows such as Mix Review, Routing Review, Project
Organizer, bridge/session checks, audio analysis, or MIDI export, read:

- [Runtime Usage](runtime-usage.md)
- [MCP Runtime Scope](../contracts/mcp-runtime-scope.md)
- [Safety Contract](../concepts/safety-contract.md)
- [Analysis Workflow Contract](../concepts/analysis-workflow-contract.md) when
  working with Control Center reviews, project health, mix/routing/organizer
  reports, preflight, low-end analysis, or other AI-guided workflow reports.

Use bundled prompt source files only for the active workflow:

- `src/fls_pilot/context/prompts/mix-review.md`
- `src/fls_pilot/context/prompts/routing-review.md`
- `src/fls_pilot/context/prompts/project-organizer.md`

### Develop Or Maintain The Repository

For code, tests, docs, controller files, scripts, workflows, packaging, or
Knowledgebase changes, read:

- [Development Guide](development.md)

Then use the guide's task-specific links. For architecture, public-surface,
safety-posture, protocol/controller, entrypoint, capability, or trust-boundary
work, also read:

- [Architecture Governance](../contracts/architecture-governance.md)
- `agent-docs/machine/architecture-governance.snapshot.json`

### GitHub Operations

For issues, PRs, roadmap planning, releases, CI, security, hotfixes, reverts,
API probes, backports, or review-only work, read:

- [GitHub Playbook](github-playbook.md)
- [GitHub Workflow Governance](../engineering/github-workflow-governance.md)
- `agent-docs/project/ROADMAP.github.md`

Then use the focused prompt source file for the exact operation.

## Context Rule

Agents should start narrow and only expand context when blocked. Runtime agents
should not read development or GitHub-operation documents unless the user task
requires repository maintenance.
