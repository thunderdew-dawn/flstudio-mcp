# Workflows

fls-pilot is designed around producer workflows rather than one-off API calls.
The safe default is read-only diagnosis first, then one explicit reversible
change only after approval.

## Mix Review

Mix Review reads live mixer and project context to find clipping, headroom,
balance, routing, and low-end risks.

![Mix Review results](../assets/control-center-mix-review-2.png)

<video controls muted playsinline preload="metadata" style="width: 100%; max-width: 960px;">
  <source src="../assets/ai-apply-gain-staging-example.mp4" type="video/mp4">
</video>

Use prompts like:

```text
Scan my mix first. Do not change anything yet. Tell me the safest next action.
```

## Low-End Analysis

Low-End Analysis focuses on bass/sub structure, mono compatibility, suspicious
stereo width, and master headroom.

![Low-end analysis details](../assets/control-center-low-end-analysis-2.png)

## Routing Audit

Routing Audit reviews mixer routes, bus structure, channels that skip groups,
and fragile send/return layouts. Cleanup remains proposal-first.

![Routing Audit overview](../assets/control-center-routing-audit.png)

<video controls muted playsinline preload="metadata" style="width: 100%; max-width: 960px;">
  <source src="../assets/ai-based-mixer-routing-example.mp4" type="video/mp4">
</video>

## Project Organizer

Project Organizer finds naming, color, grouping, and routing cleanup
candidates. It can propose one reversible cleanup step at a time.

![Project Organizer scan](../assets/control-center-project-organizer.png)

<video controls muted playsinline preload="metadata" style="width: 100%; max-width: 960px;">
  <source src="../assets/ai-color-my-tracks-example.mp4" type="video/mp4">
</video>

## Plugin and EQ Workflows

fls-pilot can inspect already-loaded plugins and configure supported parameters
when parameter ranges are known. It cannot load or insert plugins.

<video controls muted playsinline preload="metadata" style="width: 100%; max-width: 960px;">
  <source src="../assets/ai-set-highpass-on-eq-batch-example.mp4" type="video/mp4">
</video>

## Composition

Composition tools can generate scale-aware melodies, chords, and patterns. The
assistant should preview notes first and wait for approval before writing to
the Piano Roll.

<video controls muted playsinline preload="metadata" style="width: 100%; max-width: 960px;">
  <source src="../assets/ai-generate-bassline-example.mp4" type="video/mp4">
</video>

## Project Health and Preflight

Project Health combines mix, routing, organization, and export-readiness checks
into a single read-only overview.

![Project health status](../assets/control-center-flstudio-project-health-status.png)

## Safe Operating Pattern

For any workflow that might write to FL Studio:

1. Scan first.
2. Explain the finding.
3. Propose one reversible action.
4. Ask for explicit approval.
5. Apply one rollback unit.
6. Report before/after and rollback details.
