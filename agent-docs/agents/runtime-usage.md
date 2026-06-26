# Runtime/MCP Usage

Use this mode to operate FLStudioPilot with a live FL Studio session. The
binding scope rules are in
[MCP Runtime Scope](../contracts/mcp-runtime-scope.md).

## Startup Protocol

1. Read `fl://agent-briefing`.
2. Read `fl://status`. If the bridge is unavailable, diagnose the connection
   before attempting live FL work.
3. Use the following MCP resources when available and relevant:
   - Agent Briefing and Status.
   - Project, Transport, Channels, Mixer, and Patterns.
   - Safety Contract, Tool Policy, and Runtime Usage.
   - Supported Capabilities, API Limits, and Write Safety.
4. Search the Knowledgebase before using FL API values, plugin parameters,
   automation/REC events, or MIDI mappings.
5. Prefer current workflow and consolidated domain tools over low-level calls.
6. Keep the first pass read-only and scoped to the active user intent.

Repository source is not runtime evidence. Do not inspect it during ordinary
FLStudioPilot usage unless the user explicitly asks for repository
development, implementation, debugging, testing, release, CI, security, or
architecture work.

## Tool-Choice Matrix

| User intent | Preferred path | Narrow alternative |
|---|---|---|
| Bridge/session health | `fl://agent-briefing`, `fl://status` | `fl_transport(action="ping")` |
| Project/export readiness | `fl_check_project_preflight`, `fl_project_health_overview` | Capped project resources |
| Mix diagnosis | `fl_review_mix`, `fl_review_low_end_stereo` | Mixer reads or a read-only batch |
| Routing review | `fl_review_routing`, `fl_plan_routing_cleanup` | Routing/channel reads |
| Project organization | `fl_plan_project_cleanup` | Channel, mixer, and playlist reads |
| Channel, mixer, pattern, playlist | Consolidated domain tool | Matching capped resource |
| Effect or loaded-plugin parameters | `fl_effect`, `fl_plugin` | Parameter read plus Knowledgebase |
| Piano Roll | `fl_piano_roll` | Readback-limit or dry-run guidance |
| Audio file analysis | `fl_audio_analysis`, `fl_extract_melody` | Use Runtime jobs for core features; validate the source path first |
| MIDI export | `fl_export_midi` | Validate the arrangement spec first |
| Values and mappings | Knowledgebase tools | `kb_search`, then a specific `kb_get` |

## Write Protocol

Persistent writes are proposal-first:

1. Scan or read current state.
2. Explain the finding and propose exactly one reversible change.
3. State the risk and exact target.
4. Obtain explicit user approval.
5. Apply the smallest practical write or one named rollback unit.
6. Read back affected state where supported.
7. Report before/after, changelog/change id, and rollback path.
8. Stop after the verified change and wait for direction.

If snapshot, target selection, API support, readback, or rollback is unclear,
remain read-only or provide a dry-run, probe, or manual alternative.

## Hard Limits

Do not use or claim:

- Raw FL API/controller escape hatches.
- Plugin loading or insertion.
- Playlist clip placement, movement, editing, or deletion.
- Pattern or clip deletion.
- Project open, new, save-as, or render automation.
- Broad UI automation.
- Unsafe automation recording.
- Full-FLP snapshot or restore.

Piano Roll generated-script writes remain undo-backed and must state readback
limitations. Loading plugins and arranging playlist clips stay manual.

## Runtime Definition Of Done

- Live claims came from current MCP resources/tools.
- Evidence mode, prerequisites, freshness, confidence, assumptions, and limits
  are visible for analysis workflows.
- Writes, if any, were explicitly approved, rollback-backed, scoped, and read
  back where supported.
- Unsupported behavior was reported as a limitation, not as completed work.

Switch to Repository Development Mode only when the task actually becomes
repository maintenance.
