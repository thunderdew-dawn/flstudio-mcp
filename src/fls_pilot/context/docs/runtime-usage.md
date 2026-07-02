# Runtime Usage

Compact startup path for agents that use FLStudioPilot with FL Studio.
This is the right context for user-facing workflows such as Mix Review, Routing
Review, Project Organizer, audio analysis, MIDI export, and bridge/session
checks.

## Startup Protocol

1. Read `fl://agent-briefing`.
2. Read `fl://status`; if the bridge is down, troubleshoot connection before
   live FL work.
3. Use MCP resources, `kb_search`, `kb_get`, and capped project resources before
   any repository file reads or large tool calls.
4. Choose a current workflow/domain tool. Avoid raw FL API calls and removed
   one-off aliases.
5. For write-capable workflows, scan/read-only first, propose exactly one
   reversible next action with a risk level, and ask for explicit confirmation
   before mutation.
6. After one approved write, read back where supported, report before/after plus
   rollback or `change_id`, then stop and wait for user direction.

## Tool-Choice Matrix

| User intent | Preferred high-level/workflow tool | Token-saving domain/read alternative |
|---|---|---|
| Check bridge/session health | `fl://agent-briefing`, `fl://status` | `fl_transport(action="ping")` |
| Project export readiness | `fl_check_project_preflight`, `fl_project_health_overview` | `fl://project`, `fl://mixer`, `fl://channels` |
| Diagnose mix problems | `fl_review_mix`, `fl_review_low_end_stereo` | `fl_mixer(action="list")`, `fl_batch` read batch |
| Review routing | `fl_review_routing`, `fl_plan_routing_cleanup` | `fl_get_routing_all`, `fl_channel(action="list")` |
| Organize names/colors/routes | `fl_plan_project_organization`, `fl_apply_organization_plan` | `fl_plan_project_cleanup`, `fl_channel`, `fl_mixer`, `fl_playlist` reads |
| Channel Rack edits | `fl_channel` | `fl://channels` |
| Mixer edits | `fl_mixer` | `fl://mixer` |
| Pattern or playlist metadata | `fl_pattern`, `fl_playlist` | `fl://patterns` |
| Effect slot/native EQ edits | `fl_effect` | `fl_effect` read actions |
| Already-loaded plugin params | `fl_plugin` | `fl_plugin(action="list_params")`, `kb_get_parameter_spec` |
| Piano Roll notes/transforms | `fl_piano_roll` | Readback-limit reports and dry-run plans |
| Many reads or grouped writes | `fl_batch` | Capped resources for first pass |
| Audio file analysis | `fl_audio_analysis`, `fl_extract_melody` | Use Runtime jobs for core features; validate the user-provided file path first |
| MIDI export | `fl_export_midi` | Validate arrangement spec before file write |
| Values, ranges, mappings, pitfalls | Knowledgebase tools | `kb_search`, then specific `kb_get` |

## Token-Saving Strategy

- Start with `fl://agent-briefing`, `fl://status`, and capped resources.
- Use MCP resources and Knowledgebase tools before repository file reads.
- Treat repository docs and source files as maintenance context, not normal
  runtime context.
- Use domain reads or `fl_batch` for known narrow state; avoid broad workflow
  calls until the user intent is clear.
- Keep detail calls scoped to the active track, channel, pattern, plugin, or
  workflow plan.

## Runtime Definition Of Done

- The selected tool path is current and Knowledgebase-informed.
- Writes, if any, are rollback-backed and verified by readback where supported.
- Write-capable workflows presented a risk level, asked for explicit
  confirmation, applied only one reversible change per confirmation, and stopped
  after the before/after report.
- Unsupported API behavior is stated as a limit, not implied as completed work.
- Public docs, MCP context, and Knowledgebase are updated when public MCP
  behavior changes.
- Verification covers the smallest meaningful resource/tool/test surface.

## When To Expand Context

Switch to `AGENTS.md` and `agent-docs/` only when the task changes repository
files, tests, issues, PRs, releases, roadmap planning, CI, security, or
backports.
