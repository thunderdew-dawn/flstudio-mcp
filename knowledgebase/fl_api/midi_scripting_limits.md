# MIDI Scripting Limits

- **Date:** 2026-06-18
- **Agent/Author:** Codex
- **Topic:** MIDI SysEx wire-size governance for the FL controller bridge.
- **Affected File/API:** `src/fls_pilot/protocol.py`,
  `src/fls_pilot/connection.py`,
  `fl_controller/FLStudioPilot/device_FLStudioPilot.py`,
  `device.midiOutSysex`.
- **Context:** The bridge transports base64-encoded JSON in both directions.
  There is no transport-level chunking or reassembly.
- **Observation:** Approximately 1000 final wire bytes are reported reliable,
  while messages around 2000 bytes were previously observed to disappear.
  Base64 expansion, the 13-byte protocol header, and F0/F7 framing all count
  toward the limit.
- **Tested Values:** Offline worst-case serialization measured a 64-step full
  response at approximately 3071 bytes, 126 floating-point peaks at
  approximately 1575 bytes, and a full 64-step write at approximately
  9579 bytes. The compact `response_too_large` envelope is approximately
  115 bytes.
- **Result:** Protocol v3 enforces `MAX_SYSEX_WIRE_SAFE = 1000`. The host
  rejects oversized requests before MIDI send. The controller replaces an
  oversized response with a bounded `response_too_large` error. Step reads,
  step writes, mixer peak reads, and plugin parameter scans use bounded pages
  or groups.
- **Confidence Level:** `implementation_verified` for serialization guards and
  offline tests; `user_reported` for the physical MIDI loss threshold.
- **Source/Method:** User-provided transport observations, source inspection,
  deterministic JSON/base64 wire-size tests, and focused unit tests.
- **Valid Ranges:** Final request or response including F0/F7 must be no more
  than 1000 bytes. Step read pages accept at most 16 requested steps and may
  return fewer when selected fields require more space. Server-side step write
  windows contain at most five distinct step indices.
- **Example:** Use `channel_get_steps` with `start`, `count <= 16`, and
  `include=["grid","vel"]`; continue from `next_start`.
- **Known Pitfalls:** A JSON payload below 1000 bytes can still exceed the wire
  limit after base64 encoding and framing. A response-only guard does not make
  oversized write or rollback requests safe.
- **Reproduction Steps:** Serialize the response envelope using compact JSON,
  base64-encode it, add the 13-byte protocol header and F0/F7, then compare the
  resulting length to `MAX_SYSEX_WIRE_SAFE`.
- **Open Questions:** Physical-loopback reliability should be re-measured on
  each supported OS/MIDI backend before increasing the limit.
- **Next Recommended Action:** Run the rollback-safe live probes with controller
  build `channels-v40` and keep the 1000-byte limit unless repeated measurements
  justify a lower value.
