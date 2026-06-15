# Composition Scale Writer Prompt

Use this when the user wants to compose melodic or harmonic content based on a
raga, scale, or chord structure in the active FL Studio pattern.

## First Reads

- `fl://agent-briefing`
- `fl://channels`
- `fl://patterns`
- `fls://capabilities/write-safety`
- `fls://docs/runtime-usage`
- `fls://docs/safety-contract`

## Workflow

1. Confirm bridge/session health.
2. Ask the user which scale, raga, or key they want to use (if not specified).
3. Use `fl_scale_list` to show available scales.
4. Use `fl_scale_get` to retrieve the specific scale/raga intervals and note set.
5. Generate the melody, note sequence, or chord voicings as a **preview** and
   present them to the user **before** any write.
6. Wait for explicit user confirmation of the proposed note content.
7. Only after confirmation:
   - Use `fl_write_raga_melody` for melodic lines.
   - Use `fl_write_raga_chords` for harmonic content.
8. After writing, read back the pattern state and report what was written.

## Stop Conditions

Stop when:

- No target pattern or channel has been selected by the user;
- The scale or raga cannot be resolved;
- The user has not confirmed the note preview;
- Rollback cannot be guaranteed;
- The user asks for audio rendering or direct WAV export.

## Response Shape

Return:

1. Resolved scale/raga name, root note, and intervals.
2. Preview of proposed notes or chord voicings (human-readable, before write).
3. Confirmation request.
4. If confirmed: written pattern summary with before/after note count plus
   rollback or `change_id`.
5. Any unsupported behavior (audio rendering) explicitly flagged as manual.
