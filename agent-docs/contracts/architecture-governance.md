# Architecture Governance Contract

This contract applies only to architecture, public-surface, safety-posture,
protocol/controller, capability, entrypoint, and trust-boundary changes.

## Governed Snapshot

`agent-docs/machine/architecture-governance.snapshot.json` is the governed
architecture snapshot. It is a compact machine-readable map, not a replacement
for source, tests, generated static analysis, or detailed concept documentation.

Do not load or update it for routine code, documentation, or test work.

## Generated Architecture Analysis

`agent-docs/machine/architecture-analysis.snapshot.json` is the full generated
static architecture analysis. Do not load it by default for coding tasks.

Prefer the scoped generated slices under `agent-docs/machine/architecture/`:

- `index.snapshot.json` — choose the correct slice for the task.
- `mcp-surface.snapshot.json` — slim MCP tools/resources/prompts surface index.
- `mcp-tools/*.snapshot.json` — module-specific MCP tool inventories; load only the affected module.
- `runtime.snapshot.json` — Runtime host, daemon RPC, reports, workflow execution.
- `controller-surface.snapshot.json` — protocol commands and FL controller handlers.
- `operation-registry.snapshot.json` — operations, safety classes, snapshot/readback/restore metadata.
- `analysis-workflows.snapshot.json` — workflow reports, evidence, scoring, freshness, Control Center panels.
- `safety-trust.snapshot.json` — write contract, forbidden capabilities, trust boundaries.
- `entrypoints.snapshot.json` — package, CLI, daemon, doctor, Control Center and controller entrypoints.
- `project.snapshot.json` and `import-graph.snapshot.json` — project inventory and dependency/refactor context.
- `data-state.snapshot.json` — Knowledgebase, packaged context, templates, report/state paths.
- `quality-observations.snapshot.json` — generated audit observations and notable risks.

Use the full generated analysis only for architecture audits, release
preparation, drift checks, or when refreshing the governed snapshot from a
current static scan.

## Mandatory Consultation

Read this contract and the governed snapshot before changing:

- Public MCP tool surface.
- Packaged MCP resources or prompts.
- Operation registry structure or safety classification.
- Safety classes, safety-layer entry points, or write contracts.
- Runtime workflows, workflow declarations, or analysis declarations.
- Protocol commands or wire format.
- FL controller handlers.
- Control Center workflow panels or their Runtime ownership.
- Bridge, daemon, Runtime, MIDI, generated-script, or other trust boundaries.
- Package/CLI entrypoints or public CLI behavior.
- Supported, forbidden, manual-only, or API-limited capabilities.

For coding work, also load only the scoped generated snapshot slices that match
the affected surface. Start with
`agent-docs/machine/architecture/index.snapshot.json` to choose the slice.

## Change Sequence

For a governed change:

1. Identify the affected component, public surface, safety class, and trust
   boundary.
2. Change source, documentation, and tests first.
3. Run the smallest relevant checks.
4. Update `agent-docs/machine/architecture-governance.snapshot.json` when a
   governed fact changed, or explicitly state why governed facts remain
   unchanged.
5. Update only the affected scoped generated slice or slices under
   `agent-docs/machine/architecture/` when generated architecture facts changed.
6. Include an Architecture Diff in the handoff or PR:
   - components added, removed, or re-owned;
   - public surfaces added, removed, or renamed;
   - safety posture or write contract changes;
   - protocol/controller changes;
   - trust-boundary changes;
   - supported/forbidden capability changes;
   - governed snapshot updated or intentionally unchanged;
   - scoped generated slices updated or intentionally unchanged.
7. Apply the STOP rule below.

For non-governed changes, do not touch snapshots unless generated facts actually
changed.

## Scoped Snapshot Update Rules

After coding changes, ask:

- Did a public MCP surface, prompt, resource, or safety annotation change?
- Did Runtime, daemon, report storage, workflow execution, freshness, or
  observation ownership change?
- Did a protocol command, wire format, bridge behavior, or controller handler
  change?
- Did workflow registry, reports, evidence, scoring, health aggregation, or
  Control Center workflow ownership change?
- Did a persistent-write operation, snapshot/readback/restore builder, safety
  class, trust boundary, forbidden capability, or manual-only capability change?
- Did an entrypoint, packaging command, dependency boundary, or generated state
  path change?

If yes, update the affected slice or slices. If no, state in the handoff or PR:

```text
Architecture snapshots unchanged because no governed or generated architecture fact changed.
```

Regenerate the full static analysis and all scoped slices before beta/stable
releases or after broad architecture, registry, runtime, protocol, controller,
or Control Center workflow refactors.

## Human-Approval STOP Rule

Stop for human approval before treating the work as ready to merge or release
when any of these changes:

- Public MCP tool, resource, or prompt behavior.
- Public CLI or Control Center workflow behavior.
- Safety posture, safety class, approval gate, rollback, or write contract.
- Runtime ownership, bridge/daemon boundary, or another trust boundary.
- Supported, forbidden, manual-only, or API-limited actions.
- Protocol command/wire surface or FL controller handler surface.
- Entry points or externally visible integration behavior.

At the STOP point, provide the Architecture Diff, evidence, verification, and
rollback/migration implications. Human approval is a governance gate; it does
not authorize an unsafe FL Studio write.

## No STOP Required

The STOP rule does not apply to:

- Typos, formatting, comments, or ordinary README edits.
- Link/path corrections with no packaged public behavior change.
- Small test fixes that preserve behavior.
- Internal refactors with unchanged public surface, safety posture, protocol,
  controller behavior, capabilities, and trust boundaries.
- Snapshot corrections that only align metadata with already-approved source.

If impact is uncertain, classify the work as governed and request review.

## Snapshot Quality Rules

- Record stable ownership, surfaces, boundaries, safety classes, and source
  paths; avoid copying large source inventories.
- Do not claim live FL Studio state.
- Do not guess tool counts, protocol versions, workflow ids, or capabilities.
- Tie volatile counts to an executable baseline check.
- Keep JSON valid, deterministic, and reviewable.
- Update `as_of` only when governed content is reviewed.
- Generated analysis slices must remain derived from the full static analysis;
  do not hand-edit slice facts without regenerating or clearly documenting why.

## Review Questions

- Is the public surface intentional and tested?
- Does every persistent write still enter through an approved safety path?
- Are Runtime and Control Center ownership boundaries unchanged or explicit?
- Are protocol and controller changes synchronized?
- Are supported and forbidden capability claims still accurate?
- Does the governed snapshot describe the resulting architecture without
  duplicating implementation detail?
- Are scoped generated slices updated only where the coding scope changed?
