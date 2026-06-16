# Development Guide

Use this path when changing code, tests, docs, scripts, controller files,
Knowledgebase files, workflows, packaging, or project behavior.

## Mandatory First Reads

Before changing code, tests, docs, scripts, controller files, skill files, evals, or roadmap state, read these files and follow them as binding project instructions:

- `agent-docs/engineering/standards.md`
- `agent-docs/concepts/safety-contract.md`
- `agent-docs/concepts/api-capability-audit.md`
- `agent-docs/concepts/analysis-workflow-contract.md`
- `agent-docs/agents/knowledgebase-protocol.md`
- `agent-docs/project/ROADMAP.github.md`

If any file conflicts with an ad-hoc prompt, stop and surface the conflict before implementing. The safety contract, API capability audit, Knowledgebase protocol, and roadmap scope are not optional.

For GitHub planning, issue/PR work, roadmap execution, releases, dependency updates, security alerts, bug triage, reviews, hotfixes, reverts, documentation-only changes, API probes, or backports, additionally read:

- `agent-docs/agents/github-playbook.md`

## Working Mode

- Act as a senior, pragmatic software engineer.
- Inspect the repo before changing it. Read surrounding code, existing tool
  patterns, tests, safety layer, protocol constants, controller handlers, and
  registration style.
- For implementation work, explicitly inspect the relevant parts of
  `agent-docs/project/ROADMAP.github.md`, `agent-docs/concepts/api-capability-audit.md`,
  `src/fls_pilot/safety.py`, `src/fls_pilot/protocol.py`, the FL controller
  script, existing tool modules, and focused tests/scripts before editing.
- For non-trivial implementation slices, produce a short implementation plan
  before editing and confirm the slice is dependency-correct and rollback-safe.
- Before building anything new, check whether the functionality already exists
  under a different name or can be composed from existing safe primitives.
- Prefer existing project patterns over new abstractions.
- For Control Center reviews, Mix Review, Routing Review, Project Organizer,
  Project Health, Preflight, Low-End Analysis, Export Readiness, and other
  AI-guided workflow reports, follow the Analysis Workflow Contract. Do not add
  private report shapes, private scoring meanings, or hidden broad FL call
  sequences; add compatibility adapters during migration instead.
- Use established patterns: protocol constants, controller handlers,
  `safety.safe_write`, `safety.safe_write_group`, Piano Roll safety helpers,
  focused tests/scripts, and FastMCP registration style.
- Keep edits small, coherent, and backport-friendly.
- Preserve all user and uncommitted changes. Never revert unrelated work.
- Use English for commits, code comments, docstrings, and repo documentation.

## Implementation Checklist

For every new FL-mutating tool, add or update:

- Protocol command constants, if needed.
- FL controller handler.
- Snapshot scope.
- Restore operation.
- Readback verification.
- Safety-layer integration via the established safety helpers.
- Tool annotations and docstring explaining safety behavior.
- Static audit compatibility.
- Focused script/unit test or rollback-safe live smoke script.
- Roadmap/API audit/docs note when behavior or scope changes.

## Verification Expectations

Run the smallest meaningful checks for the changed area, then broaden when the
blast radius justifies it:

- Compile checks for touched Python code.
- `scripts/audit_tool_safety.py --fail-on-gaps`.
- `scripts/audit_tool_safety.py --fail-on-missing-safety-docs --format json`
  when tool annotations or docstrings change.
- Focused script tests for changed areas.
- FastMCP registration/tool-count checks when tool registration changes.
- Analysis workflow contract tests or adapter coverage when Control Center
  workflows, workflow reports, prerequisites, freshness, scoring, or health
  aggregation change.
- Rollback-safe live smoke tests when FL Studio is available and the change
  touches live behavior.

If repo-wide `pytest` or `ruff` failures are pre-existing, report them
separately and do not churn unrelated code.

At handoff, summarize changed files, verification run, remaining risks or API
limits, and the next recommended roadmap slice.

## Local Environment

- Python target: 3.12 for current development on this machine. Package metadata
  still supports Python 3.10+ unless changed deliberately.
- On macOS, commands importing pip, XML, or audio dependencies may need:

```bash
export DYLD_LIBRARY_PATH="/usr/local/opt/expat/lib:${DYLD_LIBRARY_PATH:-}"
```

- Prefer `rg` and `rg --files` for search.
- Use `apply_patch` for manual file edits.
- Do not use destructive Git commands unless explicitly requested.

## Live FL Studio Procedure

- Start the TCP daemon yourself when live tests require it.
- Confirm heartbeat and `fl_transport(action="ping")` before live work.
- Confirm the controller build marker expected by the current code.
- Read current state before writing.
- For live write tests, write a temporary value, verify readback, rollback
  immediately, and verify restoration.
- If MIDI routing, script reload, or restart state is uncertain, diagnose the
  connection before changing code.
- Stop daemons you started and leave playback stopped/recording disarmed after
  tests.

## Workspace And File Artifact Protocol

To keep the workspace clean and maintain context for generated artifacts, agents
must use these output directories. Never write files directly to the root of
`scratch/` or the project root.

- Temporary scripts: `scratch/scripts/`
- Generated MIDI: `scratch/midi/`
- Analysis data and state dumps: `scratch/analysis/`
- Audio files: `scratch/audio/`
- Logs: `scratch/logs/`

Use session- or task-specific subdirectories where appropriate, for example
`scratch/analysis/YYYY-MM-DD_session_name/`.
