# Project Preflight Prompt

Use this before any export, release, or handoff to confirm the project is
free of critical health or export blockers.

## First Reads

- `fl://agent-briefing`
- `fl://status`
- `fls://capabilities/write-safety`
- `fls://docs/runtime-usage`
- `fls://docs/safety-contract`

## Workflow

1. Confirm bridge/session health.
2. Run `fl_project_health_overview` to get a high-level project health summary.
3. Run `fl_check_project_preflight` to detect export blockers.
4. Use `fl_get_guided_cleanup_context` to surface actionable cleanup steps if
   blockers are found.
5. Prioritize export- and release-blocking issues before cosmetic problems.
6. Present all blockers and their risk level clearly.
7. Propose the safest one-step remediation for the highest-priority blocker.
8. Ask for explicit confirmation before any write action.

## Stop Conditions

Stop and switch to read-only or manual guidance when:

- bridge status is unclear;
- a proposed fix requires plugin loading, rendering, or playlist clip edits;
- rollback or readback cannot be guaranteed;
- the user has not explicitly approved a specific write step.

## Response Shape

Return:

1. Bridge/session status.
2. Project health overview (critical, warning, info counts).
3. Export-blocking issues in priority order.
4. One proposed safest reversible remediation step with risk level.
5. Confirmation request before any write, or applied before/after plus rollback
   or `change_id` if already confirmed.
6. Any unsupported behavior (e.g. plugin loading) explicitly flagged as manual.
