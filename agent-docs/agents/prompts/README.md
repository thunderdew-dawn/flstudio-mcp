# MCP Prompts — Agent Guide

MCP Prompt Markdown is bundled with the server under
`src/fls_pilot/context/prompts/`. That package directory is the canonical
runtime source used by `src/fls_pilot/prompts.py`. Only runtime prompts are
registered as public MCP prompts.

## Three Layers: Prompts · Resources · Tools

| Layer | What it does | When to use |
|-------|-------------|-------------|
| **Prompts** | Guide the agent through a workflow step-by-step | Start here for user-facing tasks |
| **Resources** | Deliver compact context (project state, safety rules, API limits) | Pull before acting on FL Studio |
| **Tools** | Execute analysis, planning, or write actions | Only after reading context and obtaining approval |

> **Key rule**: MCP Prompts do **not** execute write tools automatically.
> A prompt is a guided template, not a write approval. Every write action
> still requires explicit user confirmation.

## Available Prompts

### Runtime Prompts (User-Facing)

| Prompt name | Source file | Purpose |
|-------------|------|---------|
| `mix_review` | `src/fls_pilot/context/prompts/mix-review.md` | Full mix diagnostic: headroom, clipping, low-end, stereo |
| `routing_review` | `src/fls_pilot/context/prompts/routing-review.md` | Mixer routing review and cleanup planning |
| `project_organizer` | `src/fls_pilot/context/prompts/project-organizer.md` | Naming, colors, grouping, and project cleanup |
| `project_preflight` | `src/fls_pilot/context/prompts/project-preflight.md` | Health check and export readiness before release |
| `plugin_chain_planner` | `src/fls_pilot/context/prompts/plugin-chain-planner.md` | FX chain planning with already-loaded plugins |
| `composition_scale_writer` | `src/fls_pilot/context/prompts/composition-scale-writer.md` | Raga/scale melody and chord composition |
| `audio_to_midi_or_reference_analysis` | `src/fls_pilot/context/prompts/audio-to-midi.md` | Audio analysis and optional MIDI extraction |

## Using Prompts via MCP

MCP clients that support prompts can invoke them by name:

```
GET /prompts/mix_review
GET /prompts/routing_review
GET /prompts/project_preflight
```

The prompt returns a structured message with:
1. A workflow orientation block (from the shared `WORKFLOW_REGISTRY`)
2. The full content from the corresponding Markdown file

## Workflows That Require Explicit User Approval

The following actions are **never** executed automatically — they always require
explicit user confirmation before any write occurs:

- `fl_apply_mix_adjustment` — mix level changes
- `fl_apply_routing_cleanup` — routing rewrites
- `fl_apply_project_cleanup_step` — naming/color/structure cleanup
- `fl_piano_roll (write_notes)` — Piano Roll content
- `fl_write_raga_melody` / `fl_write_raga_chords` — composition writes
- `fl_gain_stage` — gain staging
- All `fl_effect`, `fl_plugin`, `fl_mixer`, `fl_channel` write actions

## Features Intentionally Not Supported

These cannot be automated via MCP — the user must perform them manually in
FL Studio:

- **Plugin loading** — new VST/AU instances cannot be loaded via the API
- **WAV rendering / audio export** — the render pipeline is not accessible
- **Playlist clip placement** — clip editing is not reliably supported
- **Project save-as / open / new** — file I/O is not available via controller scripts
- **Guessing normalized parameter values** — use Knowledgebase evidence only

See `fls://capabilities/not-possible` for the complete list with workarounds.

## Prompt Content Maintenance

To keep documentation and MCP prompts in sync:

- Edit the Markdown files in `src/fls_pilot/context/prompts/`.
- The Python module `src/fls_pilot/prompts.py` loads content from those bundled
  files at server startup.
- Do **not** duplicate prompt content into Python code; always edit the Markdown
- For new runtime prompts, create a new `.md` file there **and** add an entry
  to `_PROMPT_MAP` in `src/fls_pilot/prompts.py`.
