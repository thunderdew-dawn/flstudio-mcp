# Runtime Job Model Contract

## Ownership And Scope

Long-running or result-heavy work runs as daemon-owned Runtime jobs under
`src/fls_pilot/runtime/`. Bounded primitive reads remain synchronous. Runtime
jobs are server state and never FL Studio project writes.

The public operations are:

- `job.submit`
- `job.status`
- `job.result`
- `job.cancel`
- `job.list`

Jobs use `fls-pilot.runtime-job.v1` and expose `queued`, `running`,
`succeeded`, `failed`, `cancelled`, `expired`, or `interrupted`.

## Durable State

The canonical store is SQLite at `~/.fls-pilot/runtime/jobs.sqlite3` with WAL
mode and a bounded busy timeout. Every transition, retry count, cancellation
request, error, and result reference is committed transactionally. Raw source
audio and large feature payloads are never stored in the jobs table.

Audio work uses a bounded executor with default concurrency one. Cancellation
is cooperative and checked between decode, resample, framing, feature, and
artifact publication phases.

## Recovery

At Runtime startup:

- queued jobs remain queued;
- running jobs become interrupted;
- cancel-requested jobs become cancelled;
- interrupted idempotent audio jobs are requeued below the retry limit;
- a valid committed result artifact promotes the job to succeeded;
- a missing or corrupt referenced artifact fails with an explicit recovery
  error.

The idempotency key is job kind, source SHA-256, extractor version, and
configuration fingerprint. Result artifacts are atomically published before
their `result_ref` is committed.

## Boundaries

Runtime jobs must not add controller commands, access the FL bridge for offline
audio analysis, modify source files, render from FL Studio, or enter the
persistent-write operation registry.
