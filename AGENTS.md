# AGENTS.md

**Create more. Check less.**

This is the compact routing entry point for AI-assisted work in
`thunderdew-dawn/fls-pilot`. Choose one mode before reading more files.

## Mode 1: Runtime/MCP Usage

Use this mode when the user wants to use FLStudioPilot with FL Studio.

Examples:

- Mix Review, Routing Audit, Project Organizer, Project Health, or Preflight.
- Export readiness, low-end checks, audio analysis, or MIDI export.
- Bridge/session status, setup diagnosis, or guided safe edits.

Read first:

- `agent-docs/agents/runtime-usage.md`
- `agent-docs/contracts/mcp-runtime-scope.md`

Then use MCP resources and tools. Start with `fl://agent-briefing` and
`fl://status` when available.

Runtime/MCP usage agents should not inspect repository source files unless the
user explicitly asks for repository development, implementation, debugging,
tests, release, CI, security, or architecture work. Repository files are
maintenance context, not evidence of current FL Studio session state.

Read only when relevant:

- `agent-docs/concepts/safety-contract.md` for write-capable workflows.
- `agent-docs/concepts/analysis-workflow-contract.md` for Control Center reviews
  and AI-guided workflow reports.
- `agent-docs/agents/knowledgebase-protocol.md` for FL API behavior, values,
  mappings, plugin parameters, automation, REC events, or MIDI details.

Do not load development, GitHub, or architecture documents during ordinary
runtime usage.

## Mode 2: Repository Development

Use this mode when changing or reviewing code, docs, tests, scripts, controller
files, Knowledgebase files, workflows, packaging, safety rules, contracts,
public behavior, or architecture.

Read first:

- `agent-docs/agents/development.md`

Then follow its task-specific routing:

- Existing persistent-write implementation or safety behavior:
  `agent-docs/concepts/safety-contract.md`
- Safety classes, write contracts, approval/rollback guarantees, or public
  persistent-write surface:
  `agent-docs/concepts/safety-contract.md` and
  `agent-docs/contracts/architecture-governance.md`
- Analysis workflows or Control Center reports:
  `agent-docs/concepts/analysis-workflow-contract.md`
- Architecture, MCP surface, protocol, controller, runtime boundary, entrypoint,
  or capability changes:
  `agent-docs/contracts/architecture-governance.md`
- FL API behavior, ranges, mappings, MIDI, automation, or reusable findings:
  `agent-docs/agents/knowledgebase-protocol.md`
- Issues, PRs, releases, CI, security, roadmap, hotfixes, or backports:
  `agent-docs/agents/github-playbook.md`

Load `agent-docs/machine/architecture-governance.snapshot.json` only for architecture,
public-surface, safety-posture, protocol/controller, or trust-boundary work. It
is not a default read for ordinary code or documentation changes.

The machine snapshot is an index of governed facts, not a substitute for the
source files and tests named inside it. Do not copy its contents into
`AGENTS.md`.

For live FL Studio verification, also follow:

- `agent-docs/agents/runtime-usage.md`

## Universal Rules

- Prefer high-level MCP tools over raw FL API calls.
- Live FL Studio state must come from MCP resources/tools, never from source
  inspection.
- Follow the shared Analysis Workflow Contract for Control Center reviews and
  AI-guided reports. Do not invent private report shapes or score meanings.
- Check the Knowledgebase before FL state writes, mixer/plugin parameters,
  automation, REC events, or MIDI work.
- Do not guess ranges, normalized values, dB/Hz mappings, event IDs, indices, or
  plugin parameters.
- No persistent FL write without explicit approval, scoped snapshot, smallest
  practical write, readback where supported, changelog entry, and rollback.
- If API support, bridge status, target selection, readback, rollback, or value
  evidence is unclear, switch to read-only, dry-run, probe-only, or manual
  guidance.
- Do not ship plugin loading/insertion, playlist clip editing, pattern or clip
  deletion, project open/new/save-as/render automation, raw escape hatches,
  broad UI automation, unsafe automation recording, or full-FLP restore claims.
- Apply the architecture STOP rule only to real public-surface, safety-posture,
  protocol/controller, supported-capability, or trust-boundary changes.
- Preserve all user and uncommitted changes. Never revert unrelated work.
- Use English for commits, code comments, docstrings, and repository docs.
- For repository-development changes, treat `evals/evals.json` as a prompt/tool-surface contract. Whenever MCP tools, workflow behavior, capability exposure, safety/rollback behavior, public API limits, prompt/resource templates, or user-facing agent expectations change, update the evals or explicitly state why no eval update is required.
