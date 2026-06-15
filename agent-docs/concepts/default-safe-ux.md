# Default Safe UX

This policy defines the default assistant behavior for user-facing workflows
that may mutate an FL Studio project. It is the product-level expression of the
write-safety contract, not a second write layer.

## Default Sequence

For every workflow that could lead to a persistent FL Studio write, the
assistant must:

1. Scan/read-only first.
2. Explain findings in normal user language.
3. Propose exactly one safest reversible next action.
4. Include a risk level for that proposal.
5. Ask for explicit confirmation before any write.
6. Apply at most one small reversible change per confirmation.
7. Read back the affected state where supported.
8. Show before/after plus rollback or `change_id` where available.
9. Stop and wait for user direction.

Dry-run and planning tools are the default for broad cleanup, export readiness,
routing restructuring, project organization, or any request that could require
several persistent writes.

## Risk Levels

| Risk level | Meaning | Default behavior |
|---|---|---|
| `read-only` | Reads state, files, or server context only. | Safe to run without write confirmation. |
| `low` | One small rollback-backed write with clear target, readback, and restore path. | Propose one action, ask for confirmation, apply one change only. |
| `medium` | Rollback-backed write, but the target is broader, grouped, or depends on state-sensitive API behavior. | Prefer dry-run; require explicit confirmation and stop after one rollback unit. |
| `high` | Technically supported only with substantial project impact, weak readback, or risky target selection. | Do not apply by default; offer manual guidance or a smaller lower-risk alternative. |
| `unsupported` | No safe API path, no rollback path, forbidden surface, or unclear evidence. | Do not write; explain the capability boundary and offer read-only, probe-only, or manual steps. |

## Proposal Shape

Every proposed write should include:

- Finding: the observed problem and evidence.
- Proposed action: one concrete reversible change.
- Risk level: `low`, `medium`, `high`, or `unsupported`.
- Safety basis: why rollback and readback are or are not available.
- Confirmation request: ask the user to approve that exact change.

Do not offer a queue of writes as the default next action. If a workflow finds
many issues, rank them and propose only the safest reversible next step.

## Applied Write Report Shape

After an approved write, report:

- What changed.
- Before/after state.
- Readback result, or the explicit readback limit.
- `change_id`, rollback command, or rollback limitation.
- What was skipped.
- Stop state: the assistant is waiting for the user's next instruction.

## Unsupported Capability Wording

Unsupported operations should be described as product/API boundaries, not raw
failures. Use wording like:

```text
I cannot apply that safely through fls-pilot because FL Studio does not expose a
verified rollback/readback path for this operation. I can give you manual steps
or run a read-only/probe-only check instead.
```

Forbidden user-facing surfaces remain forbidden even when a user asks for them:
plugin loading/insertion, playlist clip editing, pattern or clip deletion,
project open/new/save-as/render automation, raw API escape hatches, broad UI
automation, unsafe automation recording, and full-FLP restore claims.
