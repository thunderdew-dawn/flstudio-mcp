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
4. Label findings by evidence level: static routing snapshot, meter snapshot
   proxy, user-confirmed intent, or verified cleanup readback.
5. Ask the producer to confirm template/profile, track roles, and intentional
   exceptions before treating name-based or template-based findings as cleanup
   ready.
6. If cleanup is requested, run `fl_plan_routing_cleanup` before any mutation.
   Keep the plan blocked when findings are unconfirmed or proxy-only.
7. Treat cleanup as a plan unless the user explicitly approves one exact
   rollback-backed write step.
8. Include a risk level for the proposed routing change.
9. After one approved write, read back where supported, report before/after plus
   rollback or `change_id`, then stop.

## Stop Conditions

Stop when target selection, track indexing, rollback, readback, or API support
is unclear. Do not guess routing targets or silently rewrite mixer structure.
Do not treat meter activity as proof of musical intent, and do not treat
name-based role detection as confirmed routing evidence.

## Response Shape

Return:

1. Current routing risks.
2. Bus/send/grouping issues.
3. Evidence level, finding state, confidence, and limitations.
4. Cleanup-plan gating status and required user decisions.
5. One proposed cleanup step with risk level only when the plan is ready.
6. Whether the step is read-only, dry-run, or write-safe-required.
7. Confirmation request, or applied before/after plus rollback or `change_id`.
