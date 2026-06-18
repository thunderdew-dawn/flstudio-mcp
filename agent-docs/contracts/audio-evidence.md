# Audio Evidence Contract

## Trust Boundary

Audio analysis accepts user-provided or manually bounced files. It never opens,
saves, renders, or mutates an FL Studio project and never modifies, moves, or
deletes source audio.

Feature artifacts use `fls-pilot.audio-features.v1`; manifests use
`fls-pilot.audio-artifact.v1`. Feature JSON and manifests are written to
temporary siblings, validated, checksummed, and atomically promoted before a
job result reference is committed.

Raw audio is not exposed through MCP. Public responses return identifiers,
compact summaries, reports, and bounded or paginated artifact data.

## Identity And Project Association

File identity is the source SHA-256 stored in artifact metadata. It must never
be used as `AnalysisReport.project_fingerprint`.

Project association uses `fls-pilot.evidence-link.v1` and records the artifact,
Runtime session, project scope, project fingerprint, evidence kind, optional
stem role, workflow targets, timestamp, and user-confirmation state. A
`rendered_audio_features` observation is valid only when the immutable artifact
is valid and the evidence link is compatible with the current project.

Changed source content creates a new artifact and invalidates the old
association. Deleting a source file does not invalidate an already complete
immutable artifact. Ambiguous project association requires user confirmation.

## Retention

The default artifact store is
`~/.fls-pilot/audio-analysis/artifacts`. Retention targets 500 artifacts,
1 GiB, and 30-day age eligibility, then applies LRU cleanup. Artifacts used by
running jobs are protected.
