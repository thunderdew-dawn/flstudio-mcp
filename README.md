# fls-pilot

![version](https://img.shields.io/badge/version-3.0.0b1-blue)
![status](https://img.shields.io/badge/status-beta-yellow)
[![CI](https://github.com/thunderdew-dawn/fls-pilot/actions/workflows/ci.yml/badge.svg)](https://github.com/thunderdew-dawn/fls-pilot/actions/workflows/ci.yml)
![license](https://img.shields.io/badge/license-MIT-green)

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Windows](https://img.shields.io/badge/Windows-10%2F11-0078D6?logo=windows&logoColor=white)
![macOS](https://img.shields.io/badge/macOS-12%2B-000000?logo=apple&logoColor=white)
![FL Studio](https://img.shields.io/badge/FL%20Studio-2025%2B-orange)

![rollback-first](https://img.shields.io/badge/safety-rollback--first-brightgreen)
![readback](https://img.shields.io/badge/writes-readback%20gated-blue)
![api-evidence](https://img.shields.io/badge/API-evidence%20based-purple)
![no-UI-claims](https://img.shields.io/badge/limits-explicit-lightgrey)

![MCP](https://img.shields.io/badge/MCP-compatible-6f42c1)
![LLM](https://img.shields.io/badge/LLM-Claude%20%7C%20ChatGPT%20%7C%20Cursor-blueviolet)
![DAW](https://img.shields.io/badge/DAW-FL%20Studio-orange)

[![Documentation Status](https://readthedocs.org/projects/fl-studio-pilot/badge/?version=v3-alpha)](https://fl-studio-pilot.readthedocs.io/en/v3-alpha/)

![FL Studio Pilot](docs/assets/fls-pilot-logo-with-text.png)

**FL Studio control for MCP-compatible LLMs: AI mixing, composition, project cleanup, routing review, analysises and production assistance through natural language.**

## Overview

fls-pilot is a Model Context Protocol (MCP) server that lets MCP-compatible clients such as Claude Desktop, ChatGPT Desktop, Cursor, and other MCP hosts control FL Studio through FL Studio's scripting API and a safety-focused server layer.

It is built for real music-production workflows: mix diagnosis, live peak watching, project cleanup, naming and color standards, routing review, plugin-chain planning, MIDI export, piano-roll composition, audio analysis, and export-readiness checks.

The project is intentionally **rollback-first**. Supported project mutations are routed through scoped snapshots, smallest-practical writes, readback where FL Studio exposes it, changelog entries, and rollback paths. Where FL Studio's API does not expose functionality, fls-pilot states that boundary explicitly instead of pretending the assistant can do it.

## High-Level Tools

The highest-value entry points for day-to-day production work are:

1. **Mix Review:** Scan a playing mix for clipping, peak risks, and balance problems, then propose reversible fixes.
2. **Project Organizer & Naming Standard Assistant:** Rename, color, group, and route channels and mixer tracks where FL Studio exposes the required metadata.
3. **Routing Review 2.0:** Detect routing problems, unrouted channels, and fragile bus layouts; propose and apply supported fixes as rollback units.
4. **Plugin & Preset Assistant:** Suggest chains and presets based on the user's installed plugin database and preset folders.
5. **Composition & Scale Composer:** Generate chord progressions and melodies in a selected scale or mode and write them through the piano-roll bridge.
6. **Audio Clip Safe Defaults:** Inspect audio clips, apply supported safe volume defaults, find free mixer tracks, and generate manual checklists for unavailable API states.
7. **Audio Analyzer:** Analyze external audio files for tempo/key and extract melodies to MIDI when optional audio extras are installed.
8. **Project Preflight & Health Overview:** Combine mix review, routing review, organization checks, and cleanup suggestions into an export-readiness report.

## MCP Prompts, Context Resources & Knowledgebase

fls-pilot exposes three clean layers for AI agents:

| Layer | How to use | Examples |
|-------|-----------|---------|
| **Prompts** | Start here — guides the agent step-by-step | `mix_review`, `routing_review`, `project_preflight` |
| **Resources** | Pull for context before acting | `fl://agent-briefing`, `fls://capabilities/write-safety` |
| **Tools** | Execute analysis or write actions | `fl_review_mix`, `kb_search`, `fl_apply_mix_adjustment` |

> **Key safety rule**: Prompts do **not** execute write tools automatically.
> A prompt is a guided template. Every write action still requires explicit
> user confirmation before execution.

### MCP Prompts (11 total)

**Runtime / user-facing:**
`mix_review` · `routing_review` · `project_organizer` · `project_preflight` ·
`plugin_chain_planner` · `composition_scale_writer` · `audio_to_midi_or_reference_analysis`

**Dev / agent tooling:**
`api_probe` · `bug_triage` · `implementation_slice` · `release_prepare`

All prompt content lives in `docs/agents/prompts/` — the single source of truth.

### New Context Resources

**Static doc resources** (compact Markdown excerpts):

| URI | Content |
|-----|---------|
| `fls://docs/safety-contract` | Safety rules and boundaries |
| `fls://docs/api-capability-audit` | FL API capability audit excerpt |
| `fls://docs/default-safe-ux` | Write-safe UX protocol |
| `fls://docs/runtime-usage` | Startup protocol and tool-choice matrix |
| `fls://docs/knowledgebase-protocol` | When and how to record findings |
| `fls://docs/tool-policy` | Tool hierarchy and forbidden patterns |

**Capability resources** (always-available, no bridge required):

| URI | Content |
|-----|---------|
| `fls://capabilities/supported` | Confirmed-supported workflows and tools |
| `fls://capabilities/not-possible` | Hard FL API limits with workarounds |
| `fls://capabilities/api-limits` | Numerical and structural API limits |
| `fls://capabilities/write-safety` | Write protocol, approval gates, snapshot rules |

### New Knowledgebase Tools

| Tool | Purpose |
|------|---------|
| `kb_search_structured(query)` | Structured search results (path, title, snippet, confidence) |
| `kb_get_many(paths)` | Fetch multiple KB files in one call |
| `kb_get_workflow_pack(workflow)` | Curated KB excerpts for a workflow |
| `kb_get_capability(intent)` | Quick capability check for a user intent |
| `kb_explain_limit(intent)` | Hard-limit explanation with workaround |
| `fl_get_workflow_context(workflow)` | Read-only workflow orientation (resources, tools, approval gates) |

> All KB tools are backwards-compatible. `kb_search(query)` still returns a plain string.



## Requirements

- **Windows 10/11** (tested on Windows 11) or **macOS 12+** (Intel & Apple Silicon)
- **Last live-verified FL Studio build:** Producer Edition v25.2.5, build 5055, with controller build marker `channels-v39`. FL Studio 20.7+ has the required MIDI scripting foundation, but individual API behavior can be build-dependent; use `fl_transport(action="ping")` and the live smoke/probe scripts before relying on a new FL build for writes.
- **Claude Desktop** or **ChatGPT Desktop** (or any MCP client)
- **Python 3.10+**
- Virtual MIDI ports:
    - **loopMIDI** on Windows ([download](https://www.tobias-erichsen.de/software/loopmidi.html))
    - **IAC Driver** (built into macOS)
- Optional: **ffmpeg** on PATH (for MP3 analysis)

## Quickstart

> [!NOTE]
> The full, step-by-step setup guide including MIDI routing, macOS accessibility permissions, and client configuration is available in [docs/user-guide/setup.md](docs/user-guide/setup.md).

```batchfile
scripts\install_windows.bat        :: Windows: controller + server + note bridge
.venv\Scripts\fls-pilot-control-center --open
```

```shell
./scripts/install_macos.sh         # macOS: controller + server + note bridge
.venv/bin/fls-pilot-control-center --open
```

Follow the local Control Center's guided setup. It stays read-only while it
checks MIDI ports, FL Studio controller heartbeat, daemon/SSE status, MCP client
snippets, and manual actions such as opening FL Studio or running `MCP_Apply`.
After Python and the core dependencies pass, Control Center attempts to start
the local daemon automatically and reports the selected port. When Control
Center starts the SSE server, it immediately tests the MCP connection through
that SSE URL and shows the result in Guided Setup.
`MCP_Apply` is only required for note-writing/composition tools, not for
read-only review workflows.

After setup, ask the LLM assistant in plain language:

> "Scan my mix and tell me what's wrong." / "Set up a vocal chain from my plugins." / "Export this arrangement to MIDI."

## Setup & Diagnostics

fls-pilot includes a read-only Setup Doctor to diagnose connection issues.
Since the architecture involves multiple layers, the Setup Doctor separates
these components to prevent misleading "server works" results when only one
part of the stack is actually connected.

### The Three Architectural Layers

Understanding these layers is critical for troubleshooting:

1. **MCP server**: How the MCP client (your IDE or AI agent) talks to `fls-pilot` (via `stdio` or `SSE/HTTP`).
2. **Bridge / Daemon**: How the MCP server communicates with FL Studio. This layer is only relevant if TCP bridge mode (`FLS_PILOT_TRANSPORT=tcp`) is used. By default, direct MIDI is used.
3. **FL Studio controller**: The actual Python script running *inside* FL Studio that handles the events.

### First-Run Verification Flow

Before starting any write-capable workflows, follow these steps to verify your installation safely without modifying project data:

1. **Install the package** (ensure virtual environment is active).
2. **Run Setup Doctor** to get human-readable feedback:
   - **Windows (.venv)**: `.venv\Scripts\fls-pilot-doctor`
   - **macOS (.venv)**: `.venv/bin/fls-pilot-doctor`
   *(If you installed via pipx, simply run `fls-pilot-doctor`)*
3. **Review `--- BLOCKERS ---` first**.
4. **Verify MCP transport**: Ensure the default `stdio` (or `SSE/HTTP` if configured) handshake succeeds.
5. **Verify Daemon**: *Only* required if you are using TCP bridge mode. If using direct MIDI, ignore daemon warnings.
6. **Verify FL Studio controller**: Ensure the script is installed, assigned to the virtual MIDI ports, and returning a fresh heartbeat.
7. **Continue**: Once all relevant blockers are resolved, you can safely proceed to write-capable workflows.

For JSON output (useful for MCP clients or CI), run:

- **Windows (.venv)**: `.venv\Scripts\fls-pilot-doctor --format json`
- **macOS (.venv)**: `.venv/bin/fls-pilot-doctor --format json`
*(If you installed via pipx, simply run `fls-pilot-doctor --format json`)*

For release validation, smoke-test both MCP transports explicitly:

- **Windows (.venv)**: `.venv\Scripts\fls-pilot-doctor --all-transports`
- **macOS (.venv)**: `.venv/bin/fls-pilot-doctor --all-transports`
*(If you installed via pipx, simply run `fls-pilot-doctor --all-transports`)*

To print a read-only local status summary:

- **Windows (.venv)**: `.venv\Scripts\fls-pilot-status`
- **macOS (.venv)**: `.venv/bin/fls-pilot-status`
*(If you installed via pipx, simply run `fls-pilot-status`)*

The status CLI tool prints bridge/project/resource state only, clearly marks unavailable or API-limited data, and does not modify FL Studio.

To open the guided first-run and runtime Control Center:

- **Windows (.venv)**: `.venv\Scripts\fls-pilot-control-center --open`
- **macOS (.venv)**: `.venv/bin/fls-pilot-control-center --open`
*(If you installed via pipx, simply run `fls-pilot-control-center --open`)*

Default local ports are: Control Center `8766`, ChatGPT/SSE
`8080`, and TCP daemon `9787`. The Control Center detects conflicts and shows
the actual selected fallback port in status, snippets, and setup reports. When
the environment is ready, it attempts to start its own daemon automatically; a
daemon started outside Control Center is detected but not stopped by Control
Center.

## Documentation

The full documentation is available on Read the Docs:

<https://fl-studio-pilot.readthedocs.io/en/v3-alpha/>

The documentation under `/docs` is the canonical source for the Developer Contract, Knowledgebase Protocol, Engineering Standards, API limits, safety model, and token-efficient MCP design rules.

## How it Works: 8 Production Phases

FL Studio's Python API has strict boundaries. fls-pilot combines safe controller calls, local file analysis, generated Piano Roll scripts, a daemon-owned MIDI bridge, and a snapshot/rollback safety layer.

### Phase 1: Ideation & Composition

* **Audio Analysis (`fl_analyze_audio`, `fl_extract_melody`)**

  * **Limitation:** FL Studio's API cannot read or analyze arbitrary audio files directly.
  * **Workflow:** fls-pilot reads `.wav` or `.mp3` files from disk and analyzes them with Python libraries. Accurate pitch tracking is available when optional audio extras are installed.

* **Piano Roll & Scales (`fl_piano_roll`, `fl_scale_get`)**

  * **Limitation:** External programs cannot freely push notes into the Piano Roll at runtime through a direct public API.
  * **Workflow:** fls-pilot generates a temporary `MCP_Apply` script. The user arms the bridge once per session, and the daemon triggers the script through the configured shortcut.

### Phase 2: Arrangement & Structure

* **Patterns & Playlist (`fl_pattern`, `fl_playlist`)**

  * **Limitation:** Direct editing, splitting, or moving of playlist clips is API-limited.
  * **Workflow:** fls-pilot manages supported pattern creation, cloning where exposed, section markers, and track metadata.

### Phase 3 & 4: Diagnosis & Preparation

* **Audio Clip Safe Defaults (`fl_inspect_audio_clips`)**

  * **Limitation:** Deep Audio Clip settings such as Stretch Pro, Normalize, and some sample internals are not exposed.
  * **Workflow:** fls-pilot applies safe Channel Rack volume defaults where supported, checks free mixer tracks, and creates manual checklists for unavailable API states.

* **Project Organizer (`fl_channel`, `fl_mixer`, `fl_apply_color_standard`)**

  * **Safety:** Large renaming, coloring, and routing operations use scoped snapshots and named rollback units.

### Phase 5: Signal Flow & Routing

* **Routing Tools (`fl_review_routing`, `fl_apply_bus_layout`, `fl_group_tracks`)**

  * **Workflow:** fls-pilot detects routing issues, proposes bus layouts, and applies supported routing changes through rollback-safe operations.

### Phase 6: Sound Design

* **Chain Planner & Presets (`fl_setup_chain`, `fl_suggest_preset`)**

  * **Hard limit:** FL Studio's API cannot load or insert plugins.
  * **Workflow:** fls-pilot scans plugin database and preset folders, suggests suitable chains, and can configure supported parameters after the user manually loads the selected plugin.

### Phase 7: Mixing & Dynamics

* **Mix Doctor (`fl_review_mix`, `fl_mix_watch_start`)**

  * **Limitation:** A static song snapshot is not enough because audio levels change over time.
  * **Workflow:** The user plays the song while fls-pilot polls live API peak meters and stores running peak evidence for each track.

* **Knowledgebase & Intents (`fl_apply_eq_intent`)**

  * **Problem:** LLMs can hallucinate invalid plugin or DAW parameter values.
  * **Workflow:** fls-pilot checks values against Knowledgebase conversion entries and verified ranges before sending supported changes to FL Studio.

### Phase 8: Export, Health & Safety

* **Project Health Checks (`fl_check_project_preflight`)**

  * **Workflow:** Before manual audio rendering, fls-pilot can run combined mix, routing, cleanup, and export-readiness checks.

* **MIDI Export (`fl_export_midi`)**

  * **Limitation:** FL Studio's API cannot click "Render to WAV".
  * **Workflow:** fls-pilot writes standard `.mid` files directly to disk. Audio bouncing remains manual.

* **Safety Layer (`fl_rollback_last_change`)**

  * **Limitation:** FL Studio's native undo can be unreliable for API scripts.
  * **Workflow:** fls-pilot stores scoped snapshots and changelog entries for supported writes. Rollback restores the affected supported state through the MCP safety path.

## What sets it apart

fls-pilot is a production assistant, not only a note sender.

* **Rollback-first writes:** project-modifying tools use snapshots, readback where available, changelog entries, and named rollback units.
* **API-evidence discipline:** FL Studio API limits are documented and handled explicitly.
* **Knowledgebase-backed parameters:** dB, Hz, normalized values, safe ranges, and known limits are stored in the local Knowledgebase.
* **Live-probe workflow:** build-dependent behavior is verified through smoke/probe scripts before relying on it for writes.
* **Real production focus:** mix review, routing review, project organization, plugin suggestions, piano-roll composition, MIDI export, and audio-file analysis.
* **LLM client flexibility:** designed for MCP-compatible clients rather than one hardcoded assistant.

> [!IMPORTANT]
> Version 3.0 is the breaking FL Studio Pilot rename. Use `fls-pilot`,
> `fls-pilot-daemon`, `fls_pilot`, `FLStudioPilot`, and `FLS_PILOT_*`;
> old package, command, import, controller, and environment-variable aliases are not retained.

## Capability Matrix

| Area        | Capability                              | Status                 | Safety mode                                                                   | API reality                                                                                         | Tracking                                                                                         |
| ----------- | --------------------------------------- | ---------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Mix         | Mix Review / Peak Watch                 | 🟢 Stable              | 🔵 Project read-only diagnosis → approved 🛡️ rollback-safe fixes              | Live peak evidence is required while the user plays the project                                     | [area](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Aarea%3Aworkflow) |
| Project     | Organizer / Naming / Colors             | 🟢 Stable              | 🛡️ Snapshot + write + readback where supported + rollback                     | Supported where FL exposes channel and mixer metadata                                               | [area](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Aarea%3Aworkflow) |
| Routing     | Routing Review / Bus Layout             | 🟢 Stable              | 🛡️ Proposal → approved write → rollback unit                                  | Routing writes require supported FL API readback                                                    | [area](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Aarea%3Aworkflow) |
| Composition | Piano Roll / Scale Composer             | 🟢 Stable              | 🛡️ Generated script bridge + rollback-safe supported writes                   | User must arm `MCP_Apply` once per session                                                          | [area](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Aarea%3Aworkflow) |
| Plugins     | Plugin Chain Planner / Preset Assistant | 🟢 Stable / 🟠 Partial | Stable for plugin discovery, preset suggestions, and supported parameter configuration; suggest-only for unavailable plugin actions | FL Studio API can inspect/configure supported plugin parameters, but cannot load, insert, or delete plugins | [area](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Aarea%3Aapi)      |
| Audio       | Audio Analyzer / Melody Extraction      | 🟢 Stable              | 🔵 Project read-only + local file analysis                                    | Reads audio files from disk, not from the FL Studio API                                             | [area](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Aarea%3Aworkflow) |
| Export      | MIDI Export / Preflight                 | 🟢 Stable              | 🔵 Project read-only + gated file write + report                              | MIDI files are written directly to disk; audio rendering remains manual because FL API cannot click Render | [area](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Aarea%3Aworkflow) |
| Safety      | Snapshot / Changelog / Rollback         | 🟢 Stable              | 🛡️ Persistent changelog + named rollback units                                | Native FL undo is not reliable for API scripts                                                      | [area](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Aarea%3Asafety)   |

### Status Legend

| Symbol               | Meaning                                                                                              |
| -------------------- | ---------------------------------------------------------------------------------------------------- |
| 🟢 Stable            | Tested and expected to work across supported builds                                                  |
| 🔵 Beta              | Feature-complete or close to feature-complete; suitable for broader validation before stable release |
| 🟡 Alpha             | Implemented and usable, but still under active validation or affected by migration/release changes   |
| 🟠 Partial           | Useful and stable for supported parts, but constrained by FL Studio API limits                       |
| 🔵 Project read-only | Does not mutate the FL Studio project; may still analyze or write external files                     |
| 🛡️ Rollback-safe     | Persistent project writes use snapshot, readback where supported, changelog, and rollback            |
| 🚧 Planned           | Tracked but not implemented                                                                          |
| ⛔ Not possible      | Blocked by the FL Studio API, DAW internals, or UI-only behavior                                     |

## FL Studio API Reality

FL Studio's Python API is useful, but it does not expose the whole DAW. fls-pilot treats these limits as part of the product contract: supported API-based workflows are stable, while unavailable DAW or UI-only actions are documented explicitly instead of being simulated or overstated.

| Claim                         | Reality                                                       | fls-pilot behavior                                                       |
| ----------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Load plugins automatically    | ⛔ Not exposed by FL Studio's API                             | Suggests chains and presets; the user loads the chosen plugin manually   |
| Configure plugin parameters   | 🟢 Stable where plugin is loaded, mapped, and supported       | Uses safe normalized values where mappings are known                     |
| Write piano-roll notes        | 🟢 Stable through the armed script bridge                     | Generates `MCP_Apply` script output and triggers the armed bridge        |
| Move/split playlist clips     | ⛔ Not exposed by FL Studio's API                             | Uses supported pattern, marker, metadata, and checklist workflows        |
| Read live mixer peaks         | 🟢 Stable                                                     | Runs peak watch while the user plays the song                            |
| Render audio to WAV           | ⛔ UI-only,         Not exposed by FL Studio's API            | User renders manually; fls-pilot can analyze the rendered file afterward |
| Rename/color/route tracks     | 🟢 Stable where the API exposes the required metadata/actions | Uses snapshot → write → readback → changelog → rollback                  |
| Set deep Audio Clip internals | ⛔ Not API-exposed for Stretch/Normalize/sample internals     | Applies safe supported defaults and generates manual checklists          |

## Maintained fork

This repository is a materially extended and actively maintained fork of [`rosasynthesiz/flstudio-mcp`](https://github.com/rosasynthesiz/flstudio-mcp), now developed as [`thunderdew-dawn/fls-pilot`](https://github.com/thunderdew-dawn/fls-pilot).

The rename from `flstudio-mcp` to `fls-pilot` is intentional and breaking. It avoids confusion with the upstream project, prevents package and command-name collisions in distribution channels such as PyPI, and makes it clear that this fork now follows its own release path, compatibility contract, and engineering direction.

In short: `flstudio-mcp` is the respected upstream foundation; `fls-pilot` is a renamed, compatibility-breaking maintained fork with a broader client target, stricter safety/governance model, clearer API-limit documentation, and an expanded production-tooling roadmap.

We are grateful for the original work in `rosasynthesiz/flstudio-mcp`. Its concepts and implementation provided the foundation that made this fork possible. Provenance and attribution are documented in `docs/community/notice.md`.

Breaking-release sequencing and migration gates are tracked in GitHub Project #7 and [release planning issue #66](https://github.com/thunderdew-dawn/fls-pilot/issues/66).

## Project Status

The GitHub project board, issues, pull requests, milestones, and releases are the source of truth.

Public Markdown snapshots are generated from GitHub metadata by the `Sync GitHub Markdown Snapshots` workflow.

* [Roadmap source of truth: GitHub Project #7](https://github.com/users/thunderdew-dawn/projects/7)
* [Public roadmap snapshot](docs/project/ROADMAP.github.md)
* [Public changelog snapshot](docs/project/CHANGELOG.github.md)

Do not edit the generated snapshot files manually. Update the GitHub source data or the renderer scripts instead.

* [Release planning issue #66](https://github.com/thunderdew-dawn/fls-pilot/issues/66)
* [Open release blockers](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+is%3Aopen+label%3Arelease-blocker)
* [API-limited work](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Aapi-limited)
* [API-dependent work](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Aapi-dependent)
* [FL Studio API work](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Aarea%3Aapi)
* [Safety-related work](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Aarea%3Asafety)
* [Workflow-related work](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Aarea%3Aworkflow)
* [Documentation work](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Aarea%3Adocs)
* [GitHub source-of-truth items](https://github.com/thunderdew-dawn/fls-pilot/issues?q=is%3Aissue+label%3Agithub-source-of-truth)
* [Issues and support](https://github.com/thunderdew-dawn/fls-pilot/issues), plus `docs/community/support.md`
* [Security policy](docs/community/security.md)
* Generated roadmap/changelog snapshots: `docs/project/` via the `Sync GitHub Markdown Snapshots` workflow
