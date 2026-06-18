# Machine-Readable Architecture Artifacts

## Governed snapshot

`architecture-governance.snapshot.json` is the compact governed architecture
snapshot. Read it only when the Architecture Governance Contract requires it:
public MCP surface, prompts/resources, registry, protocol/controller, runtime,
Control Center workflow ownership, safety posture, trust boundaries,
entrypoints, or supported/forbidden capabilities.

This file is manually reviewable and must be updated when governed facts change.

## Full generated static analysis

`architecture-analysis.snapshot.json` is the full generated static architecture
analysis. Do not load it by default. Use it for architecture audits, release
preparation, drift checks, or when refreshing the governed snapshot from a
current static scan.

## Scoped generated slices

Use `architecture/index.snapshot.json` to select task-specific slices under
`architecture/`. MCP tool inventories are further split by module under
`architecture/mcp-tools/`. These slices are preferred for routine coding tasks because
they reduce token usage and avoid unrelated context.
