# Project Organizer Prompt

Use this when the user wants names, colors, routes, channel organization, or a
project cleanup plan.

## First Reads

- `fl://agent-briefing`
- `fl://status`
- `fls://docs/runtime-usage`
- `fls://docs/safety-contract`
- `fls://docs/default-safe-ux`

## Workflow

1. Confirm bridge/session health.
2. Read current channels, mixer, and playlist metadata through capped resources
   or domain tools.
3. Run `fl_scan_project_organization` or `fl_analyze_project_organization`,
   then run `fl_plan_project_organization` when template-aware organization is
   useful, or `fl_plan_project_cleanup` for the legacy one-step cleanup plan.
4. Present the stored organizer plan id, plan hash, blocked steps, manual
   checks, and required user decisions.
5. Store exact producer decisions with
   `fl_update_organization_plan_decision`; approved steps must be named by id.
6. Ask for explicit confirmation before mutation, including exact step ids.
7. Apply only approved stored plan steps with `fl_apply_organization_plan`, or
   one approved legacy cleanup step with `fl_apply_project_cleanup_step`, and
   only when rollback/readback are clear.
8. After the write, call `fl_get_organization_status`, report before/after plus
   rollback or `change_id`, then stop.

## Stop Conditions

Stop when target selection, color mapping, routing destination, readback, or
rollback is unclear. Do not delete patterns/clips or edit playlist clip
placement. Do not apply blocked, rejected, ignored, expired, or stale-fingerprint
organization plan steps.

## Response Shape

Return:

1. Current organization summary.
2. Proposed groups/routes/colors/names.
3. One proposed reversible step with risk level.
4. Confirmation request, or applied before/after plus rollback or `change_id`.
5. Rollback/readback notes for any write-safe-required step.
