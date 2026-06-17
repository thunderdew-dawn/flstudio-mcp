![fls-pilot logo](assets/fls-pilot-logo.svg)
# MCP Integration

fls-pilot is built for MCP-compatible clients such as Claude Desktop, ChatGPT
Desktop, Cursor, and other local MCP hosts. Users can ask in plain language,
while integrators can call resources, prompts, and tools directly.

## Recommended Agent Entry Points

Runtime agents should start with MCP context, not repository file reads:

| MCP surface | Purpose |
|---|---|
| `fl://agent-briefing` | Compact startup orientation, current tool families, safety rules, and stop rules. |
| `fl://status` | Bridge health, heartbeat age, FL version, tempo, and playback state. |
| `fl://channels`, `fl://mixer`, `fl://patterns` | Capped project summaries for first-pass orientation. |
| `fls://capabilities/supported` | Supported workflow categories. |
| `fls://capabilities/not-possible` | Hard API limits and manual workarounds. |
| `fls://capabilities/write-safety` | Approval gates and rollback-first write protocol. |

MCP prompts are available for guided workflows such as Mix Review, Routing
Review, Project Organizer, Project Preflight, Plugin Chain Planning,
Composition, and Audio Analysis.

## Domain Tools

Use high-level workflow and domain tools before low-level details:

| Area | Preferred tools |
|---|---|
| Transport | `fl_transport` |
| Mixer | `fl_mixer`, `fl_mixer_get_levels`, `fl_review_mix` |
| Channels | `fl_channel`, `fl_detect_unassigned_channels` |
| Patterns and playlist metadata | `fl_pattern`, `fl_playlist` |
| Plugins and effects | `fl_plugin`, `fl_effect`, `fl_setup_chain` |
| Piano Roll | `fl_piano_roll`, `fl_write_raga_melody`, `fl_write_raga_chords` |
| Project review | `fl_project_health_overview`, `fl_check_project_preflight` |
| Knowledgebase | `kb_search`, `kb_get`, `kb_get_workflow_pack`, `kb_explain_limit` |

Write-capable tools still require explicit user approval before project
mutation. A prompt or resource read is not approval to write.

## Client Configuration

For stdio clients, configure the `fls-pilot` command and set
`FLS_PILOT_TRANSPORT=tcp` when using the daemon.

For ChatGPT Desktop, use the SSE URL shown in Control Center. The default is:

```text
http://localhost:8080/sse
```

If Control Center selects a fallback port, use the displayed fallback URL.
