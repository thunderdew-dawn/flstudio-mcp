# Repository Development

Use this mode for code, docs, tests, scripts, controller files, Knowledgebase
files, workflows, packaging, contracts, public behavior, or architecture.

## Start Small

Read this file first, inspect the affected area, then load only the contracts
required by the change.

| Change type | Required context |
|---|---|
| Ordinary code, tests, scripts, or docs | `agent-docs/engineering/standards.md` |
| Existing persistent-write implementation or safety behavior | `agent-docs/concepts/safety-contract.md` |
| Safety classes, write contracts, approval/rollback guarantees, or public persistent-write surface | `agent-docs/concepts/safety-contract.md` and `agent-docs/contracts/architecture-governance.md` |
| Analysis workflows, reports, scoring, freshness, or Control Center panels | `agent-docs/concepts/analysis-workflow-contract.md` |
| Architecture, MCP surface, resources/prompts, registry, protocol, controller, entrypoints, capabilities, or trust boundaries | `agent-docs/contracts/architecture-governance.md` |
| FL API values, ranges, mappings, MIDI, automation, or reusable findings | `agent-docs/agents/knowledgebase-protocol.md` |
| Issues, PRs, roadmap, releases, CI, security, hotfixes, or backports | `agent-docs/agents/github-playbook.md` and `agent-docs/project/ROADMAP.github.md` |
| Live FL verification | `agent-docs/agents/runtime-usage.md` |

Read `agent-docs/machine/architecture-governance.snapshot.json` only when the Architecture
Governance Contract requires it. Do not load it for routine edits.

If a binding contract conflicts with the requested implementation, stop and
surface the conflict before changing behavior.

## Working Method

- Inspect surrounding code, existing patterns, tests, and public contracts
  before editing.
- Check whether the capability already exists or composes from safe primitives.
- Keep changes small, testable, reviewable, and easy to revert.
- Preserve user and uncommitted changes. Never revert unrelated work.
- Prefer established protocol constants, controller handlers, operation
  registry specs, safety helpers, workflow declarations, and FastMCP
  registration patterns.
- Keep the FL controller thin. Product judgement belongs server-side.
- Use English for commits, comments, docstrings, and repository documentation.

For non-trivial implementation work, state a short plan before editing.

## Architecture-Relevant Changes

Before editing an architecture-governed surface:

1. Read `agent-docs/contracts/architecture-governance.md`.
2. Consult `agent-docs/machine/architecture-governance.snapshot.json`.
3. Change source, docs, and tests first.
4. Update the snapshot, or explicitly explain why it remains unchanged.
5. Report an Architecture Diff.
6. Stop for human approval when the contract's STOP rule applies.

The STOP rule does not apply to typo fixes, normal README edits, comments,
small test corrections, or internal refactors with no public-surface, safety,
capability, protocol/controller, or trust-boundary effect.

## Write Tool Checklist

For every new persistent FL mutation, add or update:

- Protocol command and controller handler when needed.
- Operation-registry declaration.
- Scoped snapshot and restore operation.
- Smallest practical write.
- Readback verification where supported.
- Safety-layer integration.
- Changelog and rollback path.
- Public safety annotation/docstring.
- Focused tests or a rollback-safe live probe.
- Knowledgebase/API audit/docs when behavior or evidence changes.

If any part is unclear, implement read-only, dry-run, manual guidance, or a
probe instead of a user-facing write.

## Verification

Run the smallest meaningful checks for the changed area:

- Compile or focused tests for touched Python.
- `scripts/audit_tool_safety.py --fail-on-gaps` for tool/safety changes.
- Missing-safety-doc audit when public tool annotations change.
- Tool registration baseline when the FastMCP surface changes.
- Analysis contract tests for workflow/report changes.
- Rollback-safe live smoke tests only when live behavior changed and FL Studio
  is available.
- `git diff --check` for every change.

Do not claim completion without reporting the checks run and anything not run.
If failures are pre-existing, report them separately and avoid unrelated churn.

## Local Conventions

- Python target on this machine: 3.12. Package support remains 3.10+ unless
  deliberately changed.
- Prefer `rg` and `rg --files`.
- Use `apply_patch` for manual edits.
- Do not use destructive Git commands unless explicitly requested.

Generated artifacts belong under task-specific subdirectories:

- Temporary scripts: `scratch/scripts/`
- MIDI: `scratch/midi/`
- Analysis/state: `scratch/analysis/`
- Audio: `scratch/audio/`
- Logs: `scratch/logs/`

## Handoff

Summarize changed files, verification, remaining risks or API limits,
Architecture Diff when applicable, snapshot status, and whether human approval
is required by the STOP rule.
