# Rendered Audio Evidence Runtime Contract

- Date: 2026-06-18
- Agent/Author: Codex
- Topic: Runtime-owned rendered audio evidence
- Affected File/API: `fl_analyze_audio`, `analysis.workflow.run(audio_evidence)`,
  Project Health
- Context: v3.0 W5/W6 evidence workflows
- Observation: User-selected audio files can be analyzed outside FL Studio and
  represented as `rendered_audio` evidence scoped by SHA-256 file hash.
- Tested Values: `rendered_master`, `stem`, and `candidate`; stem and candidate
  duration limit 180 seconds.
- Result: Successful reports retain the source hash, evidence kind, supported
  features, unavailable metrics, and optional workflow links. Project Health
  may raise linked workflow coverage/confidence but does not change risk or
  health scores from unrelated evidence.
- Confidence Level: implementation_verified
- Source/Method: Focused unit tests and repository-wide regression suite.
- Valid Ranges: `evidence_kind` is one of `rendered_master`, `stem`,
  `candidate`; short-file limit is 0–180 seconds inclusive.
- Example: `fl_analyze_audio(path, evidence_kind="stem",
  workflow_links=["low_end_analysis"])`
- Known Pitfalls: Tempo, key, and spectral-band shares require optional audio
  dependencies. WAV-compatible files retain duration and level evidence when
  those metrics are unavailable. Audio evidence never triggers FL render,
  save, export, or mastering actions.
- Reproduction Steps: Analyze the same file twice and confirm identical
  `metadata.file.sha256` and `snapshot_id`.
- Open Questions: True loudness, phase correlation, mono cancellation, and
  multi-stem overlap remain unavailable.
- Next Recommended Action: Add new metrics only when their implementation,
  confidence semantics, and file-hash validity are tested.
