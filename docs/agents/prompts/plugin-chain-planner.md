# Plugin Chain Planner Prompt

Use this when the user wants to set up or review a plugin signal chain on a
mixer track.

> **Hard API Limit**: FL Studio plugins cannot be loaded automatically. The
> MCP server can only plan or configure plugin chains using plugins that already
> exist in the current project. If a required plugin is missing, the user must
> load it manually in FL Studio first.

## First Reads

- `fl://agent-briefing`
- `fl://mixer`
- `fls://capabilities/not-possible`
- `fls://docs/tool-policy`
- `docs/agents/runtime-usage.md`
- `docs/concepts/safety-contract.md`

## Workflow

1. Confirm bridge/session health.
2. Read `fl://mixer` to understand current track layout.
3. Inspect available plugins and effect slots on the target track using
   `fl_effect(action="list_slots")`.
4. Use `fl_list_chains` and `fl_list_installed_plugins` to understand what is
   available for planning.
5. Use `fl_setup_chain` only to configure or plan chains using plugins that
   already exist in the project. Do not attempt to load new VST/AU instances.
6. For any required plugin role that has no loaded plugin, output it explicitly
   as a **manual step** the user must complete in FL Studio.
7. Do not set normalized plugin parameter values without Knowledgebase evidence.
   Use `kb_get` or `kb_search` before any parameter write.
8. Present the full chain plan to the user before executing any write step.
9. Ask for explicit confirmation before any parameter change.

## Stop Conditions

Stop when:

- A required plugin has not been loaded by the user;
- No Knowledgebase evidence exists for a normalized parameter value;
- Rollback or readback cannot be guaranteed for a proposed write;
- The user asks for plugin installation, rendering, or WAV export.

## Response Shape

Return:

1. Current mixer track and effect slot state.
2. Proposed chain plan (each slot: plugin role, plugin name or "MISSING – manual
   load required", parameter intent).
3. Manual steps the user must complete in FL Studio before automation can
   proceed.
4. One proposed parameter write (if any), with risk level and Knowledgebase
   evidence citation.
5. Confirmation request before any write, or applied before/after plus rollback
   or `change_id` if confirmed.
6. Clear statement of any unsupported behavior (plugin loading, WAV rendering).
