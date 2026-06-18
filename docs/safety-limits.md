![fls-pilot logo](assets/fls-pilot-logo-with-title-and-slogan.png)
# Safety & Limits

fls-pilot is rollback-first. Read-only checks can run freely, but persistent
FL Studio project changes must be small, explicit, verified where FL Studio
supports readback, recorded in the change log, and rollback-capable.

## Normal Write Flow

For any workflow that might change the project, the assistant should:

1. Scan first with read-only context.
2. Explain the finding in normal user language.
3. Propose one reversible next action with a risk level.
4. Ask for explicit approval of that exact action.
5. Apply at most one approved rollback unit.
6. Read back the affected state where supported.
7. Report before/after plus rollback or `change_id`, then stop.

## Risk Levels

| Level | Meaning |
|---|---|
| `read-only` | Reads project, server, or file context without changing FL Studio. |
| `low` | One narrow rollback-backed write with clear target and restore data. |
| `medium` | Wider rollback-backed write or state-sensitive target selection. |
| `high` | Technically possible but too broad or weakly verifiable for default automation. |
| `unsupported` | No safe FL Studio API path, no rollback/readback evidence, or a forbidden surface. |

## Hard Product Boundaries

fls-pilot does not expose tools for:

- Loading or inserting plugins.
- Rendering WAV/audio from FL Studio.
- Project open, new, save-as, or broad UI automation.
- Playlist clip placement, movement, splitting, or deletion.
- Pattern or clip deletion.
- Raw FL API escape hatches.
- Full-FLP snapshot or full-project restore claims.

When FL Studio does not expose a safe API path, fls-pilot returns manual
guidance or a read-only/probe-only result instead of pretending the assistant
completed the action.

## Knowledgebase-Backed Values

Plugin parameters, mixer ranges, dB/Hz mappings, REC event IDs, and indexing
rules are not guessed. Runtime agents should use MCP resources and `kb_*`
Knowledgebase tools for compact, verified context.
