![fls-pilot logo](../assets/fls-pilot-logo.svg)
# Workflows

fls-pilot is designed around producer workflows rather than one-off API calls.
The safe default is read-only diagnosis first, then one explicit reversible
change only after approval.

## Analysis Workflows And Evidence

Project Review workflows such as Mix Review, Low-End Analysis, Routing Audit,
Project Organizer, Preflight, and Audio Evidence produce shared analysis
reports instead of private one-off results. Reports carry findings, coverage,
freshness, assumptions, limitations, proposed changes, applied changes, and
safety metadata so MCP clients and Control Center panels can reason about the
same evidence.

Evidence modes are shown explicitly:

| Mode | User meaning |
|---|---|
| Static snapshot | Current FL Studio metadata such as names, mixer controls, routing, plugins, patterns, and playlist track metadata. |
| Live runtime | Current playback or meter data, such as peaks captured while the project plays. |
| Watch window | A recent bounded meter watch, usually 8-60 seconds of a selected loud section. |
| Rendered audio | User-provided or manually bounced audio files analyzed outside FL Studio. |
| Manual check | A human step is required because the FL API cannot prove the fact. |
| Hybrid | The report intentionally combines more than one evidence mode. |

Active workflows are available in the current v3 runtime and Control Center.
Planned workflows can appear in catalogs as roadmap items, but they do not
imply an automated action is available.

## How it Works: 8 Production Phases

FL Studio's Python API is useful but has strict boundaries. This project combines safe controller calls, local file analysis, generated Piano Roll scripts, and a snapshot/rollback safety layer. The summary below explains what is automated and where FL Studio still requires manual action.

### Phase 1: Ideation & Composition (Notes & Audio)

**Audio Analysis (`fl_audio_analysis`, `fl_extract_melody`)**
- **The Limitation:** FL Studio's API cannot read or analyze audio files.
- **How it works:** `fl_audio_analysis` submits daemon-owned Runtime jobs for user-provided `.wav` or `.mp3` files, publishes compact audio feature artifacts, and powers the Control Center `/api/audio-analysis` path. `fl_extract_melody` remains available for monophonic melody-to-MIDI extraction and can use CREPE when the optional accurate audio extras are installed.

**Piano Roll & Scales (`fl_piano_roll`, `fl_scale_get`)**
- **The Limitation:** The API does not allow external programs to arbitrarily push notes directly into the Piano Roll at runtime.
- **How it works:** The assistant generates a temporary `MCP_Apply` script. A background daemon triggers the armed script with a keyboard shortcut (Cmd+Opt+Y on macOS), causing FL Studio to write the notes to the selected Piano Roll target.

### Phase 2: Arrangement & Structure

**Patterns & Playlist (`fl_pattern`, `fl_playlist`)**
- **The Limitation:** Direct editing, splitting, or moving of Audio/MIDI clips in the playlist is blocked by the API.
- **How it works:** The assistant manages supported structure such as pattern creation, pattern cloning where exposed, section markers, and track metadata through unified domain tools.

### Phase 3 & 4: Diagnosis & Preparation

**Audio Clip Safe Defaults (`fl_inspect_audio_clips`)**
- **The Limitation:** Deep Audio Clip features like "Stretch Pro" or the "Normalize" toggle are not exposed.
- **How it works:** The tools can apply safe Channel Rack volume limits, check for free mixer tracks, and generate manual checklists for Stretch/Normalize states that the FL API cannot verify.

**Project Organizer (`fl_channel`, `fl_mixer`, `fl_apply_color_standard`)**
- **Safety:** Renaming and coloring a large project uses scoped snapshots and named rollback units so supported changes can be audited and restored through the MCP safety layer.

### Phase 5: Signal Flow & Routing

**Routing Tools (`fl_review_routing`, `fl_apply_bus_layout`, `fl_group_tracks`)**
- **How it works:** Routing tools detect structural issues, propose bus layouts, and apply supported routing changes as named rollback units.

### Phase 6: Sound Design (The Strictest API Boundary)

**Chain Planner & Presets (`fl_setup_chain`, `fl_suggest_preset`)**
- **The Hard Limit:** It is technically impossible to load or insert a plugin via the FL Studio API.
- **The workflow:** The assistant scans FL Studio plugin database and preset folders on disk, suggests chains from what it finds, and can configure parameters after the user manually loads the chosen plugin.

### Phase 7: Mixing & Dynamics

**Mix Doctor (`fl_review_mix`, `fl_mix_watch_start`)**
- **The Limitation:** Static project metadata can find routing, plugin, naming,
  and rough gain risks, but it cannot prove dynamic loudness, masking, phase, or
  spectrum facts.
- **How it works:** `fl_review_mix()` defaults to Level 1 static review and
  may use current mixer peaks if FL Studio is already playing. Level 2 uses an
  explicit peak watch while the user plays a loud section. Level 3 and Level 4
  prepare rendered-master and stem/bus evidence requests for the external
  analyzer path; they list expected checks but do not invent audio conclusions.

**Knowledgebase & Intents (`fl_apply_eq_intent`)**
- **The Problem:** AI notoriously "hallucinates" plugin parameter values (e.g. setting a knob to 150% when the limit is 100%).
- **How it works:** Before sending supported parameter changes to FL Studio, the assistant checks requested values against Knowledgebase conversion entries such as `kb_get_conversion` and sends normalized values within verified ranges.

### Phase 8: Export, Health & Safety

**Project Health Checks (`fl_check_project_preflight`)**
- **How it works:** Before a manual audio render, the assistant can run combined Mix Review, Routing Review, and cleanup checks to report export-readiness risks.

**Audio Export (`fl_export_midi`)**
- **The Limitation:** The API cannot click "Render to WAV".
- **How it works:** The tools write standard `.mid` files directly to disk for arrangement exports. Audio bouncing remains manual.

**The Safety Layer (`fl_rollback_last_change`)**
- **The Limitation:** FL Studio's native Undo (Ctrl+Z) is highly unreliable for API scripts.
- **How it works:** The MCP safety layer stores scoped snapshots and changelog entries for supported writes. Calling rollback restores the affected supported state through the MCP rollback path.

---

## Detailed Examples

## Mix Review

Mix Review reads live mixer and project context to find clipping, headroom,
balance, routing, and low-end risks.

![Mix Review results](../assets/control-center-mix-review-2.png)

[![Mix Review workflow](../assets/ai-apply-gain-staging-example.gif)](../assets/ai-apply-gain-staging-example.gif)

Use prompts like:

```text
Scan my mix first. Do not change anything yet. Tell me the safest next action.
```

Mix Review evidence levels:

| Level | Name | What it can support |
|---|---|---|
| 1 | Static Mix Review | Default. Uses names, routing, mixer controls, plugins, template context, and other project metadata. If FL Studio is already playing, current mixer peaks may support clipping/headroom checks as momentary live evidence. Findings without audio evidence are marked heuristic, provisional, or low confidence. |
| 2 | Live Peak Watch | Uses a fresh 8-60 second meter watch for peak, clipping risk, headroom, and hot-track evidence. Playback is user-guided or explicitly triggered from the GUI as a transient action. |
| 3 | Rendered Master Evidence | Prepared contract for linked rendered-master evidence and expected checks such as LUFS, true peak, clipping count, crest factor, stereo correlation, mono loss, and band energy. This beta does not calculate or claim those facts in Mix Review without external analyzer results. |
| 4 | Stem/Bus Evidence | Prepared contract for stem roles and expected checks such as kick/bass masking, low-end phase, bus balance, stem headroom, and mono compatibility. This beta does not claim masking, phase, or spectrum conclusions without external analyzer results. |

Every finding includes confidence and evidence metadata. Static HPF,
compression, EQ-overlap, and genre-profile hints are guidance, not proof.

## Low-End Analysis

Low-End Analysis focuses on bass/sub structure, mono compatibility, suspicious
stereo width, and master headroom.

![Low-end analysis details](../assets/control-center-low-end-analysis-2.png)

Low-End Analysis evidence levels:

| Level | Name | What it can support |
|---|---|---|
| 1 | Static metadata / project structure | Name, routing, plugin, color, group, and mixer-control evidence. Findings are provisional/static suspicions and cannot prove audio behavior. |
| 2 | Live playback data | Playback telemetry such as peaks, meters, channel activity, and clipping indicators. This can strengthen level/risk findings but remains limited without explicit role evidence. |
| 3 | Rendered master audio | User-rendered or user-provided master/mixdown audio. Findings are proxy-labeled low-end findings and must not claim kick, bass, sub, or stem-specific causes. |
| 4 | Role-confirmed bus/stem evidence | Rendered stems or buses with roles confirmed by explicit metadata or user decision. This is the first level that can support stem-specific low-end conclusions. |
| 5 | Deeper batch / multi-source evidence | Planned deeper diagnosis across multiple rendered channels, stems, buses, playback captures, or future evidence sources. |

## Routing Audit

Routing Audit reviews mixer routes, bus structure, channels that skip groups,
and fragile send/return layouts. Cleanup remains proposal-first.

![Routing Audit overview](../assets/control-center-routing-audit.png)

[![Routing Audit workflow](../assets/ai-based-mixer-routing-example.gif)](../assets/ai-based-mixer-routing-example.gif)

## Project Organizer

Project Organizer finds naming, color, grouping, and routing cleanup
candidates. It can propose one reversible cleanup step at a time.
For template-aware organization, `fl_plan_project_organization` creates a
stored plan with a plan hash, project fingerprint, blocked steps, manual checks,
and required user decisions. `fl_apply_organization_plan` applies only selected
approved steps from that stored plan; stale, rejected, ignored, blocked, or
expired plan steps are refused.

![Project Organizer scan](../assets/control-center-project-organizer.png)

[![Project Organizer workflow](../assets/ai-color-my-tracks-example.gif)](../assets/ai-color-my-tracks-example.gif)

## Plugin and EQ Workflows

fls-pilot can inspect already-loaded plugins and configure supported parameters
when parameter ranges are known. It cannot load or insert plugins.

[![Plugin and EQ workflow](../assets/ai-set-highpass-on-eq-batch-example.gif)](../assets/ai-set-highpass-on-eq-batch-example.gif)

## Composition

Composition tools can generate scale-aware melodies, chords, and patterns. The
assistant should preview notes first and wait for approval before writing to
the Piano Roll.

[![Composition workflow](../assets/ai-generate-bassline-example.gif)](../assets/ai-generate-bassline-example.gif)

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
