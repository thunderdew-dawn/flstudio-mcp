# Scoped Architecture Snapshots

This directory contains generated, task-scoped slices of the full static
architecture analysis. They exist to save agent context and reduce token usage.

Start with:

- `agent-docs/machine/architecture-governance.snapshot.json` for governed facts.
- `agent-docs/machine/architecture/index.snapshot.json` to choose the relevant
  generated slice.

Do not load `agent-docs/machine/architecture-analysis.snapshot.json` by default.
It is the full generated static analysis and may be too large for routine
coding work.

## Slice Selection

- MCP tools/resources/prompts: `mcp-surface.snapshot.json`, the affected
  `mcp-tools/<module>.snapshot.json` file, and `safety-trust.snapshot.json`.
- Runtime/daemon/bridge: `runtime.snapshot.json`,
  `controller-surface.snapshot.json`, and `safety-trust.snapshot.json`.
- Control Center analysis workflows: `analysis-workflows.snapshot.json`,
  `operation-registry.snapshot.json`, and `safety-trust.snapshot.json`.
- Operation registry or persistent writes: `operation-registry.snapshot.json`,
  `safety-trust.snapshot.json`, and, when protocol-backed,
  `controller-surface.snapshot.json`.
- Dependency or module-boundary refactors: `project.snapshot.json` and
  `import-graph.snapshot.json`.
- Release/audit work: `quality-observations.snapshot.json`,
  `project.snapshot.json`, and any affected surface slice.

## Update Rule

After coding changes, update only the affected scoped slice or slices. Update
`architecture-governance.snapshot.json` only when governed facts changed.

If no governed or generated architecture fact changed, the handoff or PR should
say:

```text
Architecture snapshots unchanged because no governed or generated architecture fact changed.
```

Regenerate the full static analysis and all scoped slices before beta/stable
releases or after broad architecture, registry, runtime, protocol, or Control
Center workflow refactors.
