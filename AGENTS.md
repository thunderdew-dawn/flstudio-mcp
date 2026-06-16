# AGENTS.md

**Create more. Check less.**

This is the repository entry point for AI-assisted work in `thunderdew-dawn/fls-pilot`.
Choose the smallest role-specific context path before reading more files.

## Choose Your Role First

### A) Use FLStudioPilot With FL Studio

Use this path when the task is to run or guide workflows such as Mix Review,
Routing Review, Project Organizer, audio analysis, MIDI export, bridge/session
health checks, or other user-facing MCP workflows.

Read:

- `agent-docs/agents/runtime-usage.md`
- `agent-docs/concepts/safety-contract.md`
- `agent-docs/concepts/analysis-workflow-contract.md` when the task involves
  Control Center reviews, Mix Review, Routing Review, Project Organizer,
  Project Health, Preflight, Low-End Analysis, or other AI-guided workflow
  reports.

Optional, only when needed:

- `agent-docs/agents/knowledgebase-protocol.md` when the task involves FL Studio API
  behavior, mixer/plugin parameters, MIDI, automation, REC events, ranges,
  mappings, or reusable findings.
- `src/fls_pilot/context/prompts/mix-review.md` when the user asks for a mix review.
- `src/fls_pilot/context/prompts/routing-review.md` when the user asks for routing review.
- `src/fls_pilot/context/prompts/project-organizer.md` when the user asks for project
  cleanup or organization.

Do not read the GitHub playbook unless the task involves issues, PRs, releases,
roadmap state, CI, security, or repository maintenance.

### B) Develop Or Maintain The Repository

Use this path when changing code, tests, docs, scripts, controller files,
Knowledgebase files, workflows, packaging, or project behavior.

Read:

- `agent-docs/agents/development.md`
- `agent-docs/concepts/safety-contract.md`
- `agent-docs/concepts/analysis-workflow-contract.md`
- `agent-docs/agents/knowledgebase-protocol.md`
- `agent-docs/engineering/standards.md`
- `agent-docs/project/ROADMAP.github.md`

For live FL Studio verification, also follow:

- `agent-docs/agents/runtime-usage.md`

### C) Work On GitHub Planning, PRs, Releases, Security, Or Roadmap

Use this path when triaging issues, planning slices, reviewing PRs, preparing
releases, handling CI failures, Dependabot, CodeQL, hotfixes, reverts, API
probes, documentation-only changes, or backports.

Read:

- `agent-docs/agents/github-playbook.md`
- `agent-docs/project/ROADMAP.github.md`

Use the focused prompt files in `src/fls_pilot/context/prompts/` when applicable.

## Universal Hard Rules

- Prefer high-level MCP tools over raw FL API calls.
- Control Center reviews and AI-guided workflow reports must follow the shared
  Analysis Workflow Contract; do not add private report shapes, private score
  meanings, or hidden broad FL call sequences.
- Check the Knowledgebase before FL state, mixer/plugin parameters, automation,
  REC events, or MIDI work.
- Do not guess FL Studio API ranges, normalized values, dB/Hz mappings, REC
  event IDs, track indices, plugin parameter indices, or valid ranges.
- No persistent FL write without scoped snapshot, smallest practical write,
  readback verification where supported, changelog entry, and rollback path.
- If API support, bridge status, target selection, readback, rollback, or value
  evidence is unclear, switch to read-only, dry-run, probe-only, or manual
  guidance.
- Do not ship plugin loading/insertion, playlist clip editing, pattern or clip
  deletion, project open/new/save-as/render automation, raw escape hatches,
  broad UI automation, unsafe automation recording, or full-FLP restore claims
  as user-facing tools.
- Preserve all user and uncommitted changes. Never revert unrelated work.
- Use English for commits, code comments, docstrings, and repository
  documentation.
