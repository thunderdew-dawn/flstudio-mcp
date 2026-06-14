# Workflows

This page explains how users normally work with fls-pilot through an AI assistant and how the safety model should be communicated.

## How Users Interact With The AI

The normal workflow is conversational:

1. The user asks for an outcome, for example "scan my mix and fix the worst
   headroom issue".
2. The assistant reads `fl://agent-briefing`, checks `fl://status`, and uses
   relevant resources such as `fl://mixer`, `fl://channels`, or specific tools.
3. The assistant scans/read-only first and explains findings in normal user
   language.
4. The assistant proposes exactly one safest reversible next action with a risk
   level and asks for explicit confirmation.
5. After confirmation, the assistant applies at most one reversible change or
   one named rollback unit.
6. The assistant reads back where supported, reports before/after plus rollback
   or `change_id`, then stops and waits.

Users do not need to know tool names, but direct tool names are available for
precision. These are both valid:

```text
Please rename mixer track 8 to Drums.
```

```text
Use fl_mixer with action set_name on track 8.
```

## Safety Classes

| Safety class | Meaning |
|---|---|
| `read-only` | Reads FL Studio, files, or server context without mutating the project. |
| `write-safe-required` | Mutates FL Studio through the safety layer with snapshot, readback, changelog, and rollback. |
| `transient` | Controls runtime state such as playback or song position; it should not persist in the project. |
| `server-state` | Changes MCP server state, safety history, dry-run mode, or rollback state. |
| `external-write` | Writes outside FL Studio, such as a MIDI file or exported change log. |

## Rollback-First Operating Model

For any persistent FL Studio write, the assistant should follow this sequence:

1. Read the current state.
2. Snapshot the affected state.
3. Make the smallest practical change.
4. Read back the result.
5. Log restore data.
6. Report what changed and how it can be rolled back.

Workflow reports use the v3 contract `fls-pilot.workflow-report.v1`. Planned
changes appear in `proposed_changes` with observed state, proposed state, safety
class, risk level, limitations or skipped work where relevant, readback
expectation, and rollback expectation. Applied changes appear in
`applied_changes` with before, requested change, after, readback status,
`change_id`, and rollback guidance from the safety changelog.

The v3 report shape intentionally omits compatibility-only legacy fields and
aliases. Use `json_report` for structured clients and `markdown_report` for
compact human-facing summaries.

## Default Safe UX

The default assistant posture is scan/read-only first. A write-capable workflow
should propose one reversible action at a time, include a risk level
(`read-only`, `low`, `medium`, `high`, or `unsupported`), and ask for explicit
confirmation before calling a write tool.

After an approved write, the assistant should show before/after, readback status
where supported, and rollback or `change_id` information. It should then stop
instead of continuing through a cleanup queue.

## Recommended Assistant Behavior

- Prefer diagnosis before mutation.
- Use dry-run mode for broad cleanup or export-readiness work.
- Apply only one approved reversible change or one named rollback unit per
  confirmation.
- Clearly state skipped actions when FL Studio API boundaries prevent safe automation.

## Related Pages

- [Prompts](prompts.md) for practical examples.
- [Default Safe UX](../concepts/default-safe-ux.md) for the risk levels and
  response shape.
- [Tool Reference](tool-reference.md) for exact tool names and safety annotations.
