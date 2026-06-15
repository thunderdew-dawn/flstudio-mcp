# Routing Review Prompt

Use this when the user wants to review routing, mixer organization, bus setup,
or send/return structure in the current FL Studio project.

## First Reads

- `fl://agent-briefing`
- `fl://status`
- `fls://docs/runtime-usage`
- `fls://docs/safety-contract`
- `fls://docs/default-safe-ux`

## Workflow

1. Confirm bridge/session health.
2. Use read-only state first.
3. Run `fl_review_routing`.
4. If cleanup is requested, run `fl_plan_routing_cleanup` before any mutation.
5. Treat cleanup as a plan unless the user explicitly approves one exact
   rollback-backed write step.
6. Include a risk level for the proposed routing change.
7. After one approved write, read back where supported, report before/after plus
   rollback or `change_id`, then stop.

## Stop Conditions

Stop when target selection, track indexing, rollback, readback, or API support
is unclear. Do not guess routing targets or silently rewrite mixer structure.

## Response Shape

Return:

1. Current routing risks.
2. Bus/send/grouping issues.
3. One proposed cleanup step with risk level.
4. Whether the step is read-only, dry-run, or write-safe-required.
5. Confirmation request, or applied before/after plus rollback or `change_id`.
