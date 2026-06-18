# Architecture Governance Contract

This contract applies only to architecture, public-surface, safety-posture,
protocol/controller, capability, entrypoint, and trust-boundary changes.

## Governed Snapshot

`agent-docs/machine/architecture-governance.snapshot.json` is the governed architecture
snapshot. It is a compact machine-readable map, not a replacement for source,
tests, or detailed concept documentation.

Do not load or update it for routine code, documentation, or test work.

## Mandatory Consultation

Read this contract and the snapshot before changing:

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

## Change Sequence

For a governed change:

1. Identify the affected component, public surface, safety class, and trust
   boundary.
2. Change source, documentation, and tests first.
3. Run the smallest relevant checks.
4. Update `agent-docs/machine/architecture-governance.snapshot.json`, or explicitly state
   why the governed facts remain unchanged.
5. Include an Architecture Diff in the handoff or PR:
   - components added, removed, or re-owned;
   - public surfaces added, removed, or renamed;
   - safety posture or write contract changes;
   - protocol/controller changes;
   - trust-boundary changes;
   - supported/forbidden capability changes;
   - snapshot updated or intentionally unchanged.
6. Apply the STOP rule below.

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

## Review Questions

- Is the public surface intentional and tested?
- Does every persistent write still enter through an approved safety path?
- Are Runtime and Control Center ownership boundaries unchanged or explicit?
- Are protocol and controller changes synchronized?
- Are supported and forbidden capability claims still accurate?
- Does the snapshot describe the resulting architecture without duplicating
  implementation detail?
