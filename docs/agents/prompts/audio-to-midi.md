# Audio to MIDI / Reference Analysis Prompt

Use this when the user wants to analyze an audio file, extract a melody or
reference data, or prepare a MIDI representation of audio content.

## First Reads

- `fl://agent-briefing`
- `fls://capabilities/supported`
- `fls://capabilities/not-possible`
- `docs/agents/runtime-usage.md`
- `docs/concepts/safety-contract.md`

## Workflow

1. Confirm bridge/session health.
2. Confirm the audio file path with the user if not provided.
3. Use `fl_analyze_audio` to extract tempo, key, and energy data from the file.
4. If melody extraction is requested, use `fl_extract_melody` (note: accuracy
   depends on audio quality and complexity).
5. Present all analysis results to the user as **analysis output only**. Do not
   write to the Piano Roll without explicit user confirmation.
6. If the user confirms they want the melody written to the Piano Roll:
   - Target a specific channel and pattern (confirm with user if unclear).
   - Only then proceed with a Piano Roll write using the extracted notes.
7. After any write, read back the pattern state and report the result.

> **Limit**: This workflow cannot directly import audio clips into the FL Studio
> playlist or create audio tracks. It analyzes audio files and may write MIDI
> note data to the Piano Roll only.

## Stop Conditions

Stop when:

- The audio file path is not accessible;
- Melody extraction confidence is too low to produce reliable MIDI;
- The user has not confirmed the write target or note content;
- The user asks for audio rendering, WAV export, or playlist clip placement.

## Response Shape

Return:

1. Audio analysis summary (tempo, key, energy, duration).
2. Extracted melody or reference notes (as a human-readable preview if
   extraction was requested).
3. Confidence assessment for extraction accuracy.
4. Confirmation request if user wants Piano Roll write.
5. If confirmed: written note summary plus rollback or `change_id`.
6. Any unsupported behavior explicitly flagged (playlist clip import, WAV
   rendering, audio track creation).
