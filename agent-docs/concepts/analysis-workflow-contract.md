# Analysis Workflow Contract

This contract applies to agents and maintainers who design, change, or use
Control Center workflows and user-facing MCP reviews such as Mix Review,
Low-End Analysis, Routing Review/Audit, Project Organizer, Project Health,
Project Preflight, Export Readiness, and future analysis workflows.

It extends the Safety Contract. It does not create a second write layer and it
does not weaken rollback, readback, or Knowledgebase requirements.

## Binding Rule

No new or materially changed Control Center workflow, MCP review, or AI-guided
producer workflow may introduce a private report shape, private score meaning,
or hidden FL Studio call sequence when the shared analysis/report structure can
represent it.

For v3.0.0-rc1, `fls-pilot.analysis-report.v1` is exclusive. Compatibility
adapters and legacy report envelopes are not accepted. See
[Analysis Report Versioning Contract](../contracts/report-versioning.md).

## Runtime Ownership

The Runtime service owns canonical session/project context, observations,
workflow declarations, reports, freshness, invalidation, durable jobs, and
audio artifact references. It is daemon-hosted for Control Center/TCP
operation and has an in-process path for direct transport. MCP workflows and
Control Center panels consume canonical Runtime responses directly.

Control Center panels must not create private workflow state, silently replace
Runtime reports, or infer current FL Studio state from static source files.
Static source can explain implementation only; current evidence must come from
the Runtime/MCP path.

## Workflow Identity Vs Agent-Facing Workflow Context

There are two workflow registries with different ownership:

| Registry | Owns | Must not own |
|---|---|---|
| `src/fls_pilot/workflows/registry.py` | Product and Runtime workflow declarations: canonical ids, status, requirements, report expectations, Control Center panels, API endpoints, health inclusion, safety notes, supported/manual/forbidden actions. | Prompt-specific tool-selection hints or dialogue sequencing. |
| `src/fls_pilot/tools/workflow_context.py` | Agent-facing guidance for prompts and `fl_get_workflow_context`: resources to read, recommended tools, approval-sensitive tools, stop rules, and unsupported actions. | Product status, Control Center catalog truth, workflow API endpoints, or report contract requirements. |

When these files mention "source of truth", read it within that scope. Product
workflow identity and UI/API availability come from the product workflow
registry. Agent orientation and prompt/tool guidance come from the workflow
context registry.

## Agent Dialogue Contract

AI-facing workflows must behave as structured diagnostic conversations, not as
opaque one-shot scans.

An agent using or improving a workflow must:

1. Start read-only and state the active evidence mode.
2. State missing prerequisites before presenting conclusions.
3. Distinguish facts, heuristics, assumptions, and manual checks.
4. Keep risk, health, coverage, and confidence separate.
5. Reuse fresh compatible observations or reports instead of making duplicate
   FL Studio calls.
6. Propose the next strongest useful evidence step when current evidence is
   weak, for example playback capture or user-provided bounced stems.
7. For write-capable flows, follow Default Safe UX: one reversible proposal,
   explicit approval, write, readback, rollback path, then stop.

An agent must not:

- Treat static mixer metadata as rendered-audio proof.
- Treat name-based role detection as fact without assumption metadata.
- Collapse health and risk into one ambiguous percentage.
- Hide stale, partial, unavailable, or downgraded evidence.
- Re-run broad FL reads merely because another panel or workflow needs the same
  data.
- Add Control Center-only scoring logic that cannot be read by MCP workflows.

## Required Workflow Declaration

Every Control Center workflow/review and user-facing MCP workflow must declare
or be migrated toward:

- `workflow_id`
- required observations
- optional observations
- prerequisites
- evidence modes it can produce
- output report type
- freshness/TTL policy
- invalidation triggers
- canonical entity types used
- risk, health, coverage, and confidence scoring policy
- supported next actions
- unsupported or manual-only actions

Examples of required observations:

- `fl_session_alive`
- `static_project_snapshot`
- `canonical_mixer_model`
- `channel_routing_snapshot`
- `routing_snapshot`
- `live_meter_window`
- `rendered_audio_features`
- `knowledgebase_policy_refs`

## Required Report Fields

Every analysis report must expose:

- `contract_version`
- `report_id`
- `workflow`
- `created_at`
- `analysis_mode`
- `project_fingerprint` when available, otherwise an explicit unknown state
- `freshness`
- `coverage`
- `prerequisites`
- `risk_score`
- `risk_band`
- `health_score`
- `confidence_score`
- `findings` or `diagnostics`
- `assumptions`
- `limitations`
- `manual_checks`
- `source_observations`
- `next_actions`
- `proposed_changes`
- `applied_changes`
- `safety`

Findings must include:

- stable finding/rule id,
- severity,
- risk score or risk contribution,
- confidence,
- evidence mode,
- canonical entity references,
- source observation references where available,
- evidence,
- assumptions and limitations,
- recommended next action.

## Evidence Modes

Workflow reports must identify which mode produced each result:

| Mode | Meaning |
|---|---|
| `static_snapshot` | FL state metadata such as names, routing, mixer controls, plugins, pattern/playlist metadata. |
| `live_runtime` | Data that requires current playback or meter capture, such as peaks and short dynamics. |
| `watch_window` | A bounded live capture window, for example full-song or loud-section peak watch. |
| `rendered_audio` | User-provided or manually bounced audio files analyzed outside FL Studio. |
| `manual_check` | A required human action because API support or evidence is insufficient. |
| `hybrid` | A report that intentionally combines more than one mode. |

Static findings may raise suspicion. They must not claim rendered-audio facts
such as real frequency clashes, sub-band stereo correlation, mono-sum
cancellation, or time-overlap unless rendered/audio evidence exists.

## Freshness And Reuse

Data from FL Studio is an observation with source, time, confidence, and
invalidation rules. Agents must prefer the future Observation Store or existing
shared report data over repeated broad reads.

Default policies to preserve in implementation plans:

- connection/heartbeat observations are short-lived, usually 1-2 seconds;
- static project snapshots are short-lived, usually 30-120 seconds;
- live meter values are very short-lived unless captured as a named watch
  window;
- rendered audio features are valid by file hash;
- reports are retained as bounded last-N records per workflow;
- raw audio artifacts are not automatically exposed through MCP.

When freshness is unclear, reports must mark the result as `stale`, `partial`,
`unavailable`, or `unknown` instead of silently using it as fresh. Rendered
audio evidence additionally follows
[Audio Evidence Contract](../contracts/audio-evidence.md) and
[Analysis Degraded-Mode Contract](../contracts/degraded-mode.md).

## Canonical FL Model

Workflow code must use canonical entities and shared count policies instead of
repeating FL Studio GUI/API quirks.

Required policies:

- Pattern display count is at least 1 even if an API count reports 0.
- Playlist track slots are fixed separately from used playlist tracks.
- Mixer special tracks such as `master` and `current` must be represented
  explicitly; user-visible counts may exclude them, but reports must state the
  policy.
- Names are labels, not stable identities.

Suggested entity ids:

- `mixer:master`
- `mixer:current`
- `mixer:4`
- `channel:10`
- `pattern:1`
- `playlist:slot:120`
- `plugin:mixer:12:slot:3`

## Health Aggregation

Project Health must be an aggregator over workflow reports and observations. It
must not become a second implementation of Mix Review, Routing Review,
Organizer, or Low-End logic.

Health may:

- read latest reports,
- check freshness,
- mark missing/stale sections,
- run cheap missing reads only when the workflow policy allows,
- compute aggregate risk/health/coverage/confidence,
- recommend the next workflow or evidence upgrade.

Health must not:

- silently recompute findings with different rules;
- average incompatible percentages;
- hide missing evidence behind a good-looking score;
- trigger unnecessary broad FL reads when fresh reports are available.

## Implementation Requirements

Any PR that adds or materially changes a Control Center workflow/review or
user-facing MCP analysis workflow must include:

- a workflow declaration or update;
- report contract coverage;
- prerequisite/freshness behavior;
- risk/health/coverage/confidence semantics;
- canonical entity handling;
- Knowledgebase references for reusable rules;
- compatibility adapter notes if legacy UI fields remain;
- focused tests for fresh, stale/partial/unavailable, and missing-prerequisite
  paths;
- Control Center tests if the workflow is shown there.

If a workflow cannot satisfy this contract yet, the PR must document the gap
and keep the behavior read-only, dry-run, probe-only, or manual-guidance-only.
