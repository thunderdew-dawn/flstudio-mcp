# Mix Review Prompt

Use this when the user wants to review the current FL Studio mix.

## First Reads

- `fl://agent-briefing`
- `fl://status`
- `fls://docs/runtime-usage`
- `fls://docs/safety-contract`
- `fls://docs/default-safe-ux`

## Workflow

1. Confirm bridge/session health.
2. Use read-only state first.
3. Run `fl_review_mix`.
4. If needed, run `fl_review_low_end_stereo`.
5. Report findings as:
   - critical mix risks
   - low-end/stereo issues
   - routing or gain-staging problems
   - evidence level and finding state
   - exactly one safest reversible next action
6. Keep Level 1 findings provisional, Level 2 findings limited to live meter
   evidence, Level 3 rendered-master findings proxy-labeled, and Level 4
   stem/bus findings limited to confirmed roles.
7. Treat rejected findings as score-neutral and ignored findings as excluded
   from fix planning.
8. Include the risk level for the proposed next action.
9. Ask for explicit confirmation before calling any write tool.
10. If confirmed, apply at most one small reversible change, read back where
   supported, report before/after plus rollback or `change_id`, then stop.

## Stop Conditions

Stop and switch to read-only, dry-run, probe-only, or manual guidance when:

- bridge status is unclear;
- target project state is unclear;
- audio evidence is missing for a hard audio claim;
- stem roles are unconfirmed for a stem-specific conclusion;
- a suggested action would require unsupported API behavior;
- rollback/readback cannot be guaranteed;
- the user asks for rendering, save-as, plugin loading, or playlist clip edits.

## Response Shape

Return:

1. Session/bridge status.
2. Mix review summary.
3. Top risks in priority order.
4. Evidence status, score status, and any required producer confirmations.
5. One proposed reversible next action with risk level.
6. Confirmation request, or applied before/after plus rollback or `change_id`.
7. Any unsupported or unverified behavior that must not be implied as complete.
