# fls-pilot — Note bridge: how it works + the ONE setup step

**Version:** 0.3.0 · **Env:** FL Studio 25.2.5, Windows · **Date:** 2026-05-25

## Why a "bridge" at all
FL's Piano-roll pyscript sandbox blocks file I/O (read AND write), so we can't
pass note data via a file. Instead the daemon **generates** `MCP_Apply.pyscript`
with the notes baked in, then fires FL's **"Run last script again" (Ctrl+Alt+Y)**
— FL re-reads the file each time, applying the fresh notes.

## Hardening (what's automated)
- **Piano roll auto-opens.** Before every note-write the controller runs
  `ui.showWindow(widPianoRoll)` (proven to open it from a *closed* state). The
  response carries `piano_roll_ensured`. → no manual "open the piano roll".
- **Channel targeting.** `fl_arrange_select_channel(n)` selects the channel; the
  piano roll follows it, so notes go to the intended instrument.

## The ONE irreducible manual step (per FL session)
**Run `MCP Apply` once from the Piano roll's Scripting menu at session start.**

This *arms* `Ctrl+Alt+Y` to target our script. There is **no API to automate
it**: the FL `ui` module exposes only browser-menu navigation + window/focus
(no run-script function), and the only ways to run a piano-roll script are the
Scripting menu or `Ctrl+Alt+Y` (which needs a prior menu run). So this one click
is unavoidable.

After that single arm, **every** note-write this session is fully automatic
(auto-open + trigger) — verified live: post-arm, writing E5 replaced C5 with no
manual action.

## Caveat
`triggered: true` only means the daemon sent the hotkey + focused FL — it can't
confirm the script ran. If notes don't appear, the cause is almost always the
un-armed state above; the `setup` field in every `apply_notes` response says so.

## Session start checklist (the whole setup)
1. loopMIDI ports up + FL open + controller loaded + daemon running
   (`fl_transport(action="ping")`).
2. **Run `MCP Apply` once** from the Piano roll Scripting menu.
That's it — arrangement / note-writes are automatic from there.
