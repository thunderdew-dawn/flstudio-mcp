# GitHub Workflow Governance

This page summarizes how `fls-pilot` is developed, tested, reviewed,
released, and operated by human maintainers and AI agents.

The workflow is rollback-first, branch-aware, issue-driven, and auditable.
Every non-trivial change should have a clear GitHub issue, a correct target
branch, a narrow pull request, and verifiable checks.

## Normative Sources

This document is a workflow summary. It must not become a second source of
truth. If it conflicts with any of the following sources, the more specific
source wins:

1. `AGENTS.md`
2. `agent-docs/agents/github-playbook.md`
3. `agent-docs/agents/development.md`
4. `agent-docs/engineering/standards.md`
5. `agent-docs/concepts/safety-contract.md`
6. GitHub Issues, Milestones, and Project #7
7. GitHub branch protection settings
8. GitHub Actions workflow files

Repository documentation, code comments, docstrings, commit messages, durable
issue comments, and pull request text must be written in English.

## Core Rules

- Do not work directly on permanent branches.
- Start from a GitHub issue or update an existing issue for every non-trivial
  change.
- Treat GitHub Issues, Milestones, and Project #7 as the planning source of
  truth.
- Keep pull requests small and reviewable.
- Preserve user work and unrelated uncommitted changes.
- Do not guess FL Studio API behavior, parameter ranges, indices, normalized
  values, dB/Hz mappings, REC event IDs, or rollback support.
- Prefer read-only, dry-run, or probe-only work whenever evidence is unclear.
- Never move release tags. Fix a bad release with a new commit, a new tag, and
  a new release.

## Permanent Branches

| Branch | Role | Use for | Do not use for |
|---|---|---|---|
| `main` | Public stable line | Current public stable state, stable release documentation, final v3 adoption | Alpha, beta, RC, or unfinished v3 work |
| `stable/v2` | v2 maintenance line | v2 bug fixes, security fixes, v2 patch releases, v2 documentation | v3 renames, breaking changes, v3 packaging changes |
| `v3/alpha` | v3 prerelease integration line | v3 alpha, beta, RC, breaking rename work, new structure, new API, v3 docs, migration | Direct merge to `main` before final v3 stable; backports to `stable/v2` |

The name `v3/alpha` is historical. Governance-wise, it is the central v3
prerelease line for alpha, beta, and release candidate work until final v3
stable is promoted to `main`.

## Branch Protection Expectations

GitHub branch protection settings are enforced by GitHub and may be stricter
than this document. Repository administrators should protect all permanent
branches where possible.

Project policy treats `main`, `stable/v2`, and `v3/alpha` as protected
branches:

- no direct human or agent commits;
- no force pushes;
- no branch history rewrites;
- no release tag rewrites;
- changes must go through short-lived branches and pull requests;
- required checks must pass before merge;
- conversations must be resolved before merge when branch protection requires
  it;
- release-relevant changes must pass Release Dry Run before tagging.

If actual GitHub branch protection differs from this policy, update the GitHub
settings or open a governance issue. Do not weaken the workflow in this file to
match an accidentally under-protected branch.

## Short-Lived Working Branches

All implementation work happens on short-lived branches.

| Branch pattern | Base branch | Purpose | Example |
|---|---|---|---|
| `feature/*` | Usually `v3/alpha` | New feature or larger implementation slice | `feature/v3-agent-json-mode` |
| `fix/*` | Affected line | Bug fix or security fix | `fix/v2-security-policy-link` |
| `docs/*` | Matching line | Documentation-only work | `docs/v3-workflow-governance` |
| `chore/*` | Matching line | Maintenance, cleanup, metadata | `chore/v3-release-metadata` |
| `release/*` | Release line | Release preparation | `release/v3-beta-1-prep` |
| `automation/*` | Created by GitHub Actions | Automated sync branches | `automation/github-markdown-snapshots` |

## Daily Start Procedure

Before changing files, inspect the current repository state:

```bash
git status
git fetch origin --prune --tags
git branch -vv
git log --oneline --decorate --graph --all -15
```

Then choose the target line deliberately:

```text
v2 maintenance or v2 patch release    -> base: stable/v2
v3 development or prerelease work     -> base: v3/alpha
public stable v2 follow-up            -> usually stable/v2, then main
final v3 stable promotion             -> PR from v3/alpha to main
```

Do not start from whichever branch happens to be checked out.

## Standard Development Workflow

```text
Read the issue
-> clarify scope, non-goals, target branch, and safety class
-> read AGENTS.md and the smallest relevant documentation path
-> update the base branch
-> create a short-lived working branch
-> make the smallest coherent change
-> run focused checks
-> commit in English
-> push the branch
-> open a pull request against the correct target branch
-> wait for CI, CodeQL, and review
-> merge according to the merge policy
-> delete the short-lived branch
```

Example for v3 documentation work:

```bash
git fetch origin --prune --tags
git switch v3/alpha
git pull --ff-only origin v3/alpha
git switch -c docs/v3-workflow-governance
```

Pull request target:

```text
docs/v3-workflow-governance -> v3/alpha
```

Example for a v2 fix:

```bash
git fetch origin --prune --tags
git switch stable/v2
git pull --ff-only origin stable/v2
git switch -c fix/v2-some-bug
```

Pull request target:

```text
fix/v2-some-bug -> stable/v2
```

If a v2 fix must also be visible on the public stable line, promote it to
`main` deliberately through a separate short-lived branch and pull request
after the `stable/v2` change is merged.

## GitHub Issues And Project #7

Issues are the operative work unit. Project #7 is the canonical roadmap and
execution board. Local chats, scratch files, and IDE sessions are execution
surfaces, not durable planning storage.

Every non-trivial issue should contain or receive:

- goal;
- context;
- acceptance criteria;
- target branch;
- non-goals;
- affected files or modules, if known;
- safety class;
- expected tests or checks;
- rollback, migration, or release notes when relevant.

Project #7 fields were verified against
<https://github.com/users/thunderdew-dawn/projects/7> with `gh api graphql`.
Use the visible GitHub field names in documentation, issues, and PR text:

| Project field | Type | Values or format | Purpose |
|---|---|---|---|
| `Status` | single select | `Todo`, `Next`, `In progress`, `Done` | Execution state |
| `Roadmap Lane` | single select | `Now`, `Next`, `Later`, `Blocked`, `Done` | Roadmap routing |
| `Priority` | single select | `P0`, `P1`, `P2`, `P3` | Priority routing |
| `Area` | single select | `Safety`, `Workflow`, `Docs`, `GitHub`, `KB`, `UX`, `API` | Functional or governance area |
| `Type` | single select | `Roadmap`, `Workflow`, `Doctor`, `Report`, `GitHub Sync` | Work type |
| `Safety` | single select | `Read-only`, `Write-safe required`, `API-dependent`, `Mixed/manual` | Safety posture |
| `PM Track` | single select | `Safety`, `Setup`, `Review`, `Preflight`, `Organizer`, `Governance`, `Research`, `Release` | Product-management track |
| `Risk` | single select | `Low`, `Medium`, `High`, `API-dependent` | Delivery or API risk |
| `Effort` | number | numeric estimate | Relative effort |
| `Blocked by` | text | issue number, dependency, or short reason | Blocking dependency |
| `PM Iteration` | iteration | configured Project iteration | Delivery iteration |

The project also has standard GitHub fields such as `Title`, `Assignees`,
`Labels`, `Linked pull requests`, `Milestone`, `Repository`, `Reviewers`,
`Parent issue`, `Sub-issues progress`, `Created`, `Updated`, `Closed`,
`Start date`, and `Target date`.

When using `gh project item-list --format json`, GitHub CLI emits JSON keys
with different casing for some fields, such as `roadmap Lane`, `pM Track`, and
`pM Iteration`. Treat those as CLI output keys only; the canonical field names
for human-facing documentation are the GitHub field names above.

Use labels and Project fields instead of restating priority and routing in every
chat prompt. Typical labels include `priority:p0` through `priority:p3`,
`area:*`, `type:*`, `read-only`, `write-safe-required`, `api-dependent`, and
`dry-run-only`.

Closed source-of-truth issues should use `Status = Done` and
`Roadmap Lane = Done`. Open release blockers need a milestone and
`Priority = P0`.

## AI Agent Rules For Repository Work

A coding agent must:

1. read the issue;
2. determine the target branch;
3. read `AGENTS.md` and the smallest relevant documentation path;
4. inspect only relevant files;
5. prefer existing repository patterns;
6. make a narrow, reviewable change;
7. run focused checks;
8. write a pull request summary with changed behavior, verification, remaining
   risk, and intentionally untouched scope.

A coding agent must not:

- work directly on `main`, `stable/v2`, or `v3/alpha`;
- move release tags;
- rewrite branch history;
- perform broad refactors without an issue;
- invent documentation that contradicts code;
- guess API boundaries;
- mutate FL Studio state unless the safety model and task scope explicitly
  allow it.

## FL Studio Safety Model

Persistent FL Studio writes must follow the safety contract:

```text
Read
-> scoped snapshot
-> smallest practical write
-> readback verification where supported
-> changelog entry
-> rollback path
-> user-facing report
```

Read-only actions are the safe default. If API support, bridge status, target
selection, readback, rollback, or value evidence is unclear, switch to
read-only, dry-run, probe-only, or manual guidance.

Do not ship user-facing tools that claim unsafe or unsupported automation, such
as raw escape hatches, broad UI automation, full-FLP restore, project open/new,
save-as/render automation, playlist clip editing, pattern deletion, clip
deletion, unsafe automation recording, or plugin loading/insertion.

## Pull Request Rules

A normal pull request should:

- target the correct permanent branch;
- reference the issue it closes or materially advances;
- keep the diff narrow;
- avoid unrelated cleanup;
- update documentation when behavior changes;
- update safety documentation when tools or FL write behavior change;
- include exact verification commands and results;
- disclose skipped checks, residual risks, and follow-up work.

Normal working branches should use squash merge to keep permanent branches
readable.

Intentional line promotions may use merge commits because the branch-level event
is historically meaningful:

```text
stable/v2 -> main
v3/alpha -> main for final v3 stable
```

Cherry-picks are allowed when only specific commits should move between lines.
When cherry-picking across v2 and v3, inspect paths and behavior deliberately;
v3 renames and structure changes can make a clean cherry-pick unsafe.

## Required Checks And Workflows

The repository uses GitHub Actions for quality, safety, project governance, and
release automation. CodeQL runs through GitHub Code Scanning Default Setup; do
not add a second advanced CodeQL workflow while Default Setup is enabled.

| Workflow | Purpose |
|---|---|
| `CI` | Installs the package, compiles Python, runs hard Ruff checks, anti-vibe audit, tool registration baseline, tool safety audits, mock bridge smoke test, and offline tests |
| `CodeQL / Default Setup` | Performs security analysis |
| `Project Automation` | Adds and syncs issues in Project #7 |
| `Project Fingerprint` | Verifies required Project #7 invariants |
| `Release Dry Run` | Builds and validates distributions without publishing a release |
| `Release` | Runs from `v*` tags, validates the tag, builds distributions, checks artifacts, and creates the GitHub Release |
| `Sync GitHub Markdown Snapshots` | Renders GitHub-backed roadmap and changelog snapshots |

Rule of thumb:

```text
CI must be green before merge.
CodeQL must be green before merge when enabled for the branch.
Release Dry Run must be green before release-relevant tagging.
Project Fingerprint must be investigated when GitHub project governance changes.
The Release workflow must be triggered by a correct tag, not replaced by manual copy/paste release steps.
```

## Docs build gate

Documentation changes are validated through the `Docs` workflow. The workflow installs the same documentation dependencies used by ReadTheDocs and runs:

`mkdocs build --strict`

Pull requests that change `docs/**`, `mkdocs.yml`, `.readthedocs.yaml`, `docs/requirements.txt`, or packaging metadata should pass the docs gate before merge.

## Definition Of Done For Normal Pull Requests

A normal PR is done only when:

- the target branch is correct;
- the scope matches the issue;
- no unintended side effects are included;
- focused local checks were run or explicitly justified as not applicable;
- CI is green;
- CodeQL is green when applicable;
- documentation was updated when behavior changed;
- tool reference, safety classes, Knowledgebase, or API audit were updated when
  the change affects them;
- Project #7 fields still reflect reality;
- the PR description explains what changed, why it changed, what was verified,
  and what was intentionally not changed.

## Release Lines

| Release type | Branch | GitHub Release state | Latest? |
|---|---|---|---|
| v2 patch | `stable/v2` | Stable release | Yes while v2 is the public stable line |
| v3 alpha | `v3/alpha` | Prerelease | No |
| v3 beta | `v3/alpha` | Prerelease | No |
| v3 RC | `v3/alpha` | Prerelease | No |
| final v3 stable | `main` | Stable release | Yes |

v3 prereleases must not be merged into `main` before final v3 stable promotion.

## Release Readiness

A release is reached only when all relevant release gates are satisfied:

1. The release scope is merged into the correct release branch.
2. `pyproject.toml` contains the matching PEP 440 version.
3. Release notes and known limitations are updated.
4. Migration notes are updated when behavior or structure changed.
5. CI is green on the release commit.
6. Release Dry Run is green for release-relevant changes.
7. The tag is created on the intended release commit only after the branch is
   ready.
8. The tag-triggered Release workflow succeeds.
9. The GitHub Release is marked as prerelease for alpha, beta, and RC tags.

A tag alone is not enough. A version bump alone is not enough. A GitHub Release
created by hand without the validated tag workflow is not enough.

## Release Stage Policy

| Stage | Meaning | Allowed | Not appropriate |
|---|---|---|---|
| Alpha | Make the rebuild visible and testable | Breaking changes, rename work, structure work, API changes, known gaps | Claims of production readiness |
| Beta | Stabilize for broader testing | Bug fixes, packaging fixes, docs, small API corrections | New large direction changes |
| RC | Candidate for final stable | Blocker fixes, security fixes, docs corrections, stabilization | New features, new breaking changes |
| Stable | Public mainline release | Conservative fixes, release documentation | Unfinished prerelease work |

Senior PM rule:

```text
Alpha asks: What must be visible and testable?
Beta asks: What blocks stabilization?
RC asks: Can this exact state become stable?
Stable asks: What can be published with low risk?
```

## Tag And Version Rules

Use SemVer-compatible Git tags with the repository's `v` prefix. Use PEP 440
versions in `pyproject.toml`.

| Git tag | Python / PEP 440 version |
|---|---|
| `v3.0.0-alpha.1` | `3.0.0a1` |
| `v3.0.0-beta.1` | `3.0.0b1` |
| `v3.0.0-rc.1` | `3.0.0rc1` |
| `v3.0.0` | `3.0.0` |
| `v2.0.1` | `2.0.1` |

Do not use compact prerelease tags:

```text
v3.0.0-alpha1
v3.0.0-beta1
v3.0.0-rc1
```

Do not move tags:

```bash
git tag -f v3.0.0-alpha.1
git push --force origin v3.0.0-alpha.1
```

Correct release repair flow:

```text
new commit
-> new version if needed
-> new tag
-> new release
-> follow-up issue for root cause if needed
```

`vX.Y.Z-stable` is accepted only for legacy or project-specific compatibility.
For new v3 releases, prefer `v3.0.0` for stable releases and
`v3.0.0-alpha.1`, `v3.0.0-beta.1`, or `v3.0.0-rc.1` for prereleases.

## Definition Of Done For Release Pull Requests

A release PR is done only when:

- the target branch is correct;
- the planned version in `pyproject.toml` matches the planned tag;
- release notes are updated;
- known limitations are documented;
- migration notes are documented when relevant;
- generated roadmap or changelog snapshots are updated through the snapshot
  workflow when needed;
- Release Dry Run is green;
- CI is green;
- CodeQL is green when applicable;
- the tag command and rollback plan are included in the PR or release issue;
- the tag is not created until after merge onto the release branch.

## Backports And Line Promotions

For a v2 fix that also belongs on `main`, use a dedicated PR rather than a
direct push:

```bash
git switch main
git pull --ff-only origin main
git switch -c fix/promote-v2-fix-to-main
git cherry-pick <commit-sha>
```

Then push the short-lived branch and open a PR to `main`.

For a fix that affects both v2 and v3:

```text
fix in stable/v2 first
-> cherry-pick or port deliberately to v3/alpha
-> adapt paths and behavior to the v3 structure
-> run target-branch checks
-> open a PR against v3/alpha
```

Do not assume the same file paths, APIs, or safety helpers exist across release
lines.

## Stop Conditions

Stop and ask for a human decision when:

- the request conflicts with `AGENTS.md`, engineering standards, or the safety
  contract;
- the correct target branch is unclear;
- Project #7 state or required fields are missing and cannot be inferred safely;
- branch protection or required checks are failing for governance reasons;
- FL Studio API support, target selection, rollback, readback, or value ranges
  are unclear;
- implementation would require prohibited automation;
- a low-reasoning implementation slice discovers architectural ambiguity;
- a security issue involves private vulnerability details or secrets;
- a release tag, version, release notes, or workflow result does not match the
  planned release.

## Quick Reference

```text
main         = public stable line
stable/v2    = v2 maintenance and v2 patch releases
v3/alpha     = v3 prerelease line for alpha, beta, and RC

feature/*    = short-lived feature branches
fix/*        = short-lived fix branches
docs/*       = short-lived documentation branches
chore/*      = short-lived maintenance branches
release/*    = short-lived release preparation branches
automation/* = GitHub Actions generated branches

Agents:
Issue -> AGENTS.md -> focused context -> narrow branch -> narrow change
-> focused checks -> PR -> CI/review -> merge

FL Studio writes:
Read -> snapshot -> smallest write -> readback -> changelog -> rollback path

Releases:
Version -> CI -> Release Dry Run -> tag on release commit -> Release workflow
```