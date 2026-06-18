# Analysis Degraded-Mode Contract

Analysis remains useful when stronger evidence is unavailable, but claims must
match the evidence actually present.

## Evidence Levels

1. Static snapshot: suspicions and metadata findings only.
2. Rendered master: whole-mix level, dynamics, tonal balance, and stereo proxy
   conclusions.
3. Aligned rendered stems: stem activity, energy, and overlap conclusions.
4. Prepared batch artifacts: full-song and multi-stem overlap analysis.

Missing or stale audio does not block Level 1 execution. It lowers coverage and
confidence, marks the affected sections `partial`, `stale`, or `unavailable`,
and supplies the next recommended evidence action.

Reports keep risk, health, coverage, and confidence separate. Proxy metrics,
including stereo and low-band stereo values, remain explicitly labeled as
proxies and are not mono-cancellation proof.

Project Health aggregates canonical reports and observations. It does not
silently recompute another workflow's findings or hide missing evidence behind
an aggregate score.
