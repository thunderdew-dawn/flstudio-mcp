# Analysis Report Versioning Contract

## Canonical Contract

`fls-pilot.analysis-report.v1` is the only accepted and emitted analysis
report contract for v3.0.0-beta.3.

> **Note on Versioning**:
> v3.0.0 RC1 was premature. The current public beta release line is v3.0.0-beta.3.
> Python/package version is 3.0.0b3. Do not treat v3/alpha as release-candidate-ready until blockers are explicitly cleared.

Every report boundary must:

- require a string `contract_version`;
- reject a missing, malformed, legacy, or unknown version;
- return the structured error code `incompatible_report_version`;
- preserve the canonical report fields without wrapping them in another report
  envelope.

`fls-pilot.workflow-report.v1`, legacy Control Center envelopes, adapter-only
score reconstruction, and compatibility migration are removed. Existing
in-memory or persisted reports using another shape are discarded.

## Ownership

The Runtime owns validation, storage, freshness, and invalidation. MCP and
Control Center consumers use canonical Runtime responses directly. They must
not infer a compatible report from partial legacy fields.

## Breaking-Release Policy

Backward compatibility is intentionally unsupported. A future report contract
requires an explicit version, validator, migration decision, release note, and
architecture review.
