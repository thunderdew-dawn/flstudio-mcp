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
3. Run `fl_plan_project_cleanup`.
4. Present a ranked plan, then propose exactly one safest reversible cleanup
   step with a risk level.
5. Ask for explicit confirmation before mutation.
6. Apply only one approved cleanup step at a time with
   `fl_apply_project_cleanup_step`, and only when rollback/readback are clear.
7. After the write, read back where supported, report before/after plus rollback
   or `change_id`, then stop.

## Stop Conditions

Stop when target selection, color mapping, routing destination, readback, or
rollback is unclear. Do not delete patterns/clips or edit playlist clip
placement.

## Response Shape

Return:

1. Current organization summary.
2. Proposed groups/routes/colors/names.
3. One proposed reversible step with risk level.
4. Confirmation request, or applied before/after plus rollback or `change_id`.
5. Rollback/readback notes for any write-safe-required step.
