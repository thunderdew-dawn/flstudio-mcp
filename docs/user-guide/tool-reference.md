# Tool Reference

This page lists read-only MCP resources, the public tool catalog, and product boundaries that should be made clear to users.

## MCP Resources

Resources are read-only context endpoints the assistant can pull without a
tool call. They are intentionally capped so automatic context reads stay small.

| Resource | What it gives the assistant |
|---|---|
| `fl://agent-briefing` | Compact startup orientation: bridge/status summary, current domain/workflow tools, token strategy, safety rules, and stop rules. |
| `fl://status` | Bridge health, heartbeat age, FL version, tempo, and playback state. |
| `fl://project` | Tempo, transport, and project-level counts. |
| `fl://transport` | Playback, recording, song position, and tempo snapshot. |
| `fl://channels` | Capped Channel Rack summary. |
| `fl://mixer` | Capped mixer-track summary. |
| `fl://patterns` | Capped pattern list. |

## Full Tool Reference

The current public MCP surface registers 94 tools: 41 `read-only`, 33
`write-safe-required`, 4 `server-state`, 2 `external-write`, 1 `transient`,
and 13 Knowledgebase/workflow-context tools registered outside the static
annotation pattern.

### Workflow Report Contract

Mix Review, Routing/Cleanup, Project Organizer, Project Health/Preflight, and
grouped cleanup flows return the v3 workflow report contract
(`fls-pilot.workflow-report.v1`). These reports separate `diagnostics`,
`proposed_changes`, `applied_changes`, and `manual_checks`, and include both
`json_report` and `markdown_report` renderings.

Proposal reports are read-only and include observed state, proposed state,
safety class, risk level, limitations or skipped work where relevant, readback
expectation, and rollback expectation. Applied reports include before,
requested change, after, readback status, `change_id`, and rollback guidance
from the safety changelog. Compatibility-only legacy report fields are
intentionally removed in v3 to keep tool output compact.

Persistent Mix Review, Routing/Cleanup, Project Organizer, and grouped cleanup
changes require an exact proposed change to be approved and then applied through
a write-safe tool with rollback/readback metadata.

### Phase 1: Ideation & Composition Tools

#### Audio Analysis
| Tool | Safety | What it does |
|---|---|---|
| `fl_analyze_audio` | `read-only` | Estimates tempo, key, and audio properties from a file. |
| `fl_extract_melody` | `read-only` | Extracts a monophonic melody from an audio file using pyin or CREPE when available. |

#### Scale Composition
| Tool | Safety | What it does |
|---|---|---|
| `fl_write_raga_melody` | `write-safe-required` | Writes a generated scale or raga melody through the Piano Roll bridge. |
| `fl_write_raga_chords` | `write-safe-required` | Writes scale-aware chords through the Piano Roll bridge. |
| `fl_scale_list` | `read-only` | Lists supported scales, modes, ragas, and related scale families. |
| `fl_scale_get` | `read-only` | Returns intervals and note mapping for a selected scale. |

### Phase 2: Arrangement & Structure Tools

#### Arrangement
| Tool | Safety | What it does |
|---|---|---|
| `fl_arrange_new_pattern` | `write-safe-required` | Creates a new named pattern and selects it. |
| `fl_arrange_select_channel` | `write-safe-required` | Selects the Channel Rack channel used as the note-bridge target. |
| `fl_arrange_clone_pattern` | `write-safe-required` | Clones a pattern, including notes where FL exposes that path. |
| `fl_arrange_add_marker` | `write-safe-required` | Adds a section marker at a bar. |

### Phase 3 & 4: Diagnosis & Preparation Tools

#### Channel & Audio Clips
| Tool | Safety | What it does |
|---|---|---|
| `fl_channel` | `write-safe-required` | Consolidated Channel Rack domain tool. Actions include list, get, get_selected, get_steps, classify, select, set_color, set_mute, set_mixer_target, set_name, set_pan, set_solo, set_steps, and set_volume. |
| `fl_detect_unassigned_channels` | `read-only` | Finds channels that likely need mixer-track assignment. |
| `fl_assign_channel_to_free_mixer_track` | `write-safe-required` | Finds a free mixer track and assigns a channel to it. |
| `fl_inspect_audio_clips` | `read-only` | Scans Audio Clips for routing, naming, and volume issues. |
| `fl_plan_audio_clip_safe_defaults` | `read-only` | Plans safe defaults (volume normalization, free track routing) for Audio Clips. |
| `fl_apply_audio_clip_safe_defaults` | `write-safe-required` | Applies safe volume limits and routing to Audio Clips with manual checklists for Stretch/Normalize. |

#### Project Organizer & Color
| Tool | Safety | What it does |
|---|---|---|
| `fl_analyze_project_organization` | `read-only` | Finds unnamed, uncolored, and ungrouped channels. |
| `fl_plan_project_cleanup` | `read-only` | Produces proposal-mode naming, routing, and cleanup changes without mutating FL Studio. |
| `fl_apply_project_cleanup_step` | `write-safe-required` | Applies approved name, color, or channel-routing cleanup changes as one rollback unit. |
| `fl_apply_naming_standard` | `write-safe-required` | Batch applies an approved naming schema (e.g., psytrance) across channels and buses. |
| `fl_apply_color_standard` | `write-safe-required` | Batch applies an approved color schema (e.g., psytrance) across channels and buses. |
| `fl_set_track_color` | `write-safe-required` | Colors one or more mixer tracks by color name or hex value. |
| `fl_set_channel_color` | `write-safe-required` | Colors one or more Channel Rack channels by color name or hex value. |

### Phase 5: Signal Flow & Routing Tools

#### Routing
| Tool | Safety | What it does |
|---|---|---|
| `fl_get_routing_all` | `read-only` | Reads the full mixer routing matrix. |
| `fl_get_channel_routing` | `read-only` | Reads channel-to-mixer routing. |
| `fl_detect_cleanup_candidates` | `read-only` | Finds likely routing or organization cleanup candidates. |
| `fl_review_routing` | `read-only` | Analyzes structural routing issues like unrouted channels or generators skipping groups. |
| `fl_plan_routing_cleanup` | `read-only` | Proposes renaming and routing fixes for structural issues. |
| `fl_apply_routing_cleanup` | `write-safe-required` | Executes batch routing fixes. |
| `fl_apply_bus_layout` | `write-safe-required` | Routes sources to newly created grouped buses (e.g., in 10-track blocks). |
| `fl_group_tracks` | `write-safe-required` | Routes selected tracks into a named bus as one grouped rollback unit. |

#### Bulk Control
| Tool | Safety | What it does |
|---|---|---|
| `fl_solo_tracks` | `write-safe-required` | Solos a resolved group of mixer tracks as one reversible operation. |
| `fl_mute_tracks` | `write-safe-required` | Mutes a resolved group of mixer tracks as one reversible operation. |
| `fl_clear_mute_solo` | `write-safe-required` | Clears mixer mute and solo states in one grouped rollback unit. |

### Phase 6: Sound Design Tools

#### Chain Planning & Presets
| Tool | Safety | What it does |
|---|---|---|
| `fl_list_chains` | `read-only` | Lists available genre or purpose chain recipes. |
| `fl_list_installed_plugins` | `read-only` | Reads installed FL plugin database entries from disk. |
| `fl_setup_chain` | `read-only` | Plans a chain from available plugins; it does not load plugins. |
| `fl_list_presets` | `read-only` | Lists presets found on disk. |
| `fl_suggest_preset` | `read-only` | Suggests presets from the local library based on a description. |
| `fl_plugin_get_preset_name` | `read-only` | Reads the current plugin preset name where FL exposes it. |
| `fl_plugin_next_preset` | `read-only` | Returns manual guidance for moving to the next preset; it does not mutate FL. |
| `fl_plugin_prev_preset` | `read-only` | Returns manual guidance for moving to the previous preset; it does not mutate FL. |

#### Plugin & Effect Slots
| Tool | Safety | What it does |
|---|---|---|
| `fl_plugin` | `write-safe-required` | Consolidated already-loaded plugin domain tool for list, list_params, get_param, and set_param. Plugin loading stays manual. |
| `fl_effect` | `write-safe-required` | Consolidated effect-slot and native EQ domain tool. Actions include get_slot, list_slots, get_track_slots_enabled, set_slot_enabled, set_slot_mix, set_track_slots_enabled, get_eq, and set_eq_band. |

### Phase 7: Mixing & Dynamics Tools

#### Mix Review
| Tool | Safety | What it does |
|---|---|---|
| `fl_review_mix` | `read-only` | Scans the mix and reports concrete issues with evidence and proposed fixes. |
| `fl_review_low_end_stereo` | `read-only` | Reports bass/sub mono-compatibility, stereo-width metadata risks, low-end layering, and Master headroom as manual-safe guidance. |
| `fl_apply_mix_adjustment` | `write-safe-required` | Applies one explicitly approved Mix Review fix through the safety layer. |
| `fl_mix_watch_start` | `read-only` | Starts full-song peak watching for better level evidence. |
| `fl_mix_watch_status` | `read-only` | Reports current peak-watch status. |
| `fl_mix_watch_stop` | `read-only` | Stops peak watching and returns a diagnosis. |
| `fl_gain_stage` | `read-only` | Proposes level trims for healthier gain staging. |
| `fl_reference_match` | `read-only` | Compares level and balance against a reference audio file. |

#### Mixing Intents
| Tool | Safety | What it does |
|---|---|---|
| `fl_apply_eq_intent` | `write-safe-required` | Applies a musical EQ intent to a target plugin or native EQ path. |
| `fl_apply_reverb_intent` | `write-safe-required` | Applies a calibrated reverb intent to an already-loaded plugin. |
| `fl_apply_delay_intent` | `write-safe-required` | Applies a calibrated delay intent to an already-loaded plugin. |
| `fl_get_track_level` | `read-only` | Reads a mixer track's current level in dB. |
| `fl_apply_compression_intent` | `write-safe-required` | Applies a calibrated compression intent, optionally level-aware. |

#### Knowledgebase
| Tool | Safety | What it does |
|---|---|---|
| `kb_search` | `unannotated` | Searches the knowledgebase for topics. |
| `kb_get` | `unannotated` | Retrieves a specific knowledgebase entry. |
| `kb_get_conversion` | `unannotated` | Gets a verified parameter conversion mapping. |
| `kb_get_parameter_spec` | `unannotated` | Gets a parameter specification from the knowledgebase. |
| `kb_list_open_questions` | `unannotated` | Lists unresolved questions from the knowledgebase. |
| `kb_record_finding` | `unannotated` | Records a new finding in the knowledgebase. |
| `kb_record_verified_finding` | `unannotated` | Records a verified finding. |

### Phase 8: Export, Health & Safety Tools

#### Project Health Checks
| Tool | Safety | What it does |
|---|---|---|
| `fl_project_health_report` | `read-only` | Reports project organization and health issues. |
| `fl_export_readiness_report` | `read-only` | Reports issues that may block or degrade export readiness. |
| `fl_project_dry_run_fix_plan` | `read-only` | Produces a fix plan without changing FL Studio. |
| `fl_project_health_overview` | `read-only` | Aggregates Mix Review, Routing Review, and Project Organizer insights into one overview. |
| `fl_check_project_preflight` | `read-only` | Export readiness checks covering clipping, unrouted channels, and manual checklists. |
| `fl_start_guided_cleanup` | `read-only` | Starts an LLM-orchestrated Guided Cleanup Mode session by returning a stateless session blueprint. |
| `fl_get_guided_cleanup_context` | `read-only` | Reconstructs the current Guided Cleanup context from fresh diagnostics without relying on conversational history. |

#### Export
| Tool | Safety | What it does |
|---|---|---|
| `fl_export_midi` | `external-write` | Writes a type-1 MIDI file to disk from an arrangement specification. |

#### Domain, Batch & Safety
| Tool | Safety | What it does |
|---|---|---|
| `fl_transport` | `write-safe-required` | Consolidated transport domain tool. Actions include ping, get_tempo, set_tempo, get_play_state, play, stop, toggle_play, record, get_song_position, set_song_position, get_time_signature, and set_time_signature. Runtime controls are transient; tempo and time-signature writes use rollback. |
| `fl_mixer` | `write-safe-required` | Consolidated mixer domain tool. Actions include list, get, get_selected, get_route, select, set_color, set_mute, set_name, set_pan, set_route, set_solo, set_stereo_separation, and set_volume. |
| `fl_pattern` | `write-safe-required` | Consolidated pattern domain tool. Actions include list, get, get_length, get_selected, find_empty, select, rename, set_color, and set_length. |
| `fl_playlist` | `write-safe-required` | Consolidated playlist-track domain tool. Actions include list, get, select, set_color, set_mute, set_name, and set_solo. Playlist clip editing is not supported. |
| `fl_piano_roll` | `write-safe-required` | Consolidated Piano Roll domain tool for undo-backed note writes, transforms, markers, and explicit readback-limit reports. |
| `fl_batch` | `write-safe-required` | Runs strict-whitelisted registry read batches or homogeneous persistent-write batches through one named rollback unit. |
| `fl_get_project_state` | `read-only` | Reads project-level state such as tempo, time signature, and counts. |
| `fl_mixer_get_levels` | `read-only` | Reads mixer peak levels. |
| `fl_take_snapshot` | `server-state` | Captures MCP safety-layer snapshot data for inspection. |
| `fl_get_change_history` | `read-only` | Lists recent MCP changelog entries. |
| `fl_get_change_log_summary` | `read-only` | Returns a markdown table summary of recent rollback units and IDs. |
| `fl_export_change_log` | `external-write` | Exports the MCP changelog to a JSON file on disk. |
| `fl_rollback_last_change` | `server-state` | Rolls back the latest MCP change. |
| `fl_rollback_change` | `server-state` | Rolls back a specific change by change ID. |
| `fl_set_dry_run` | `server-state` | Enables or disables dry-run mode for planned changes. |

## Boundaries To State Clearly To Users

- The app cannot load or insert plugins. Users load plugins manually, then the
  assistant can inspect and configure already-loaded plugins.
- The app does not expose project open, new, save-as, render, pattern deletion,
  playlist clip editing, or raw UI automation tools.
- Piano Roll writes use an armed `MCP_Apply` script and FL undo for rollback;
  structured note readback is still API-limited.
- FL Studio API behavior can be build-dependent. The known-working baseline is
  documented in the README, and live probes should be run before relying on a
  new FL Studio build for write-heavy work.
