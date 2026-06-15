# GitHub Playbook

This playbook describes how humans, local coding agents, and review agents
should use the configured GitHub setup for day-to-day project work. GitHub
Issues, Milestones, and Project #7 are the planning source of truth; local
agent chats are execution surfaces, not durable planning storage.

## Shared Rules

- Start from the canonical project:
  <https://github.com/users/thunderdew-dawn/projects/7>
- Do not create duplicate roadmap projects. Project
  #7 is canonical.
- Every non-trivial change starts with a GitHub issue or updates an existing
  one.
- Always use the repository's issue and PR templates (e.g., `.github/ISSUE_TEMPLATE/*` and `.github/pull_request_template.md`) to structure the body when creating or updating issues and pull requests.
- Keep `agent-docs/project/ROADMAP.github.md` and `agent-docs/project/CHANGELOG.github.md`
  as generated snapshots backed by the snapshot workflow.
- Use small PRs. Each PR should close or materially advance one issue.
- Branching, permanent branch protection expectations, release lines, and tag
  rules are summarized in
  [GitHub Workflow Governance](../engineering/github-workflow-governance.md).
- Persistent FL Studio writes still require snapshot, readback, changelog, and
  rollback. If evidence is unclear, ship read-only, dry-run, probe-only, or
  manual guidance.

## Roles

- Human owner: decides product intent, accepts or rejects features, and resolves
  priority conflicts.
- High-reasoning planning agent: reads the issue, repo standards, and relevant
  code; produces implementation plans, dependency order, safety analysis, and
  agent slices.
- Low-reasoning implementation agent: executes one narrow, pre-approved slice
  at a time with minimal exploration.
- Review agent: checks diffs, tests, safety posture, and issue/PR alignment.

## Token-Saving Defaults

- Put durable context in GitHub issues, not in repeated chat prompts.
- Give agents one issue number and one slice at a time.
- Tell agents which files to inspect first.
- Ask planning agents for concise output: assumptions, dependencies, slices,
  commands, and stop conditions.
- Ask implementation agents to avoid broad repo scans after the planning agent
  has identified the relevant files.
- Use GitHub labels and Project fields to route work instead of restating
  priorities in every chat.
- Project #7 field names are case-sensitive in human-facing documentation:
  `Status`, `Roadmap Lane`, `Priority`, `Area`, `Type`, `Safety`, `PM Track`,
  `Risk`, `Effort`, `Blocked by`, and `PM Iteration`.

## Use Case 1: Human Wants A Local IDE Agent To Implement An Idea

### Human Actions

1. Open a Feature Request or Workflow Request issue.
2. Add the intended outcome, safety class, relevant FL API evidence, and known
   unsupported boundaries.
3. Assign labels and Project fields:
   - labels: `priority:p0` through `priority:p3`, `area:*`, `type:*`,
     `read-only`, `write-safe-required`, `api-dependent`, or `dry-run-only`;
   - Project fields: `Status`, `Roadmap Lane`, `Priority`, `Area`, `Type`,
     `Safety`, and any relevant `PM Track`, `Risk`, `Effort`, `Blocked by`, or
     `PM Iteration` value.
4. Set `Roadmap Lane` to the intended Project #7 lane.
5. Start the local IDE agent with the prompt below.

### Local Agent Prompt

```text
Work on GitHub issue #<number> in thunderdew-dawn/fls-pilot.

Rules:
- Read AGENTS.md, agent-docs/engineering/standards.md, agent-docs/project/ROADMAP.github.md,
  and the issue.
- Treat GitHub issue/project state as the planning source of truth.
- Do not perform FL Studio writes.
- If the task needs live FL evidence, prepare a read-only or rollback-safe probe
  plan instead of guessing.
- Implement the smallest coherent slice that satisfies this issue.
- Update docs/API audit/verification history/Knowledgebase only when the change
  requires it.
- Run focused checks, then summarize changed files, verification, remaining
  risk, and next slice.
```

### Completion Criteria

- PR references the issue.
- Required local checks pass.
- GitHub CI and CodeQL pass.
- Project issue fields remain accurate after merge.

## Use Case 2: Agent Prepares The Next Roadmap Item For Multi-Agent Execution

The high-reasoning agent prepares work. Lower-reasoning agents execute only the
prepared slices in order.

### Human Actions

1. Pick the next item from Project #7, usually `Roadmap Lane = Now`, then
   `Priority = P0/P1`.
2. Assign or confirm the milestone and labels.
3. Ask a high-reasoning planning agent for a token-efficient implementation
   plan and slice queue.
4. Require the planning agent to save the accepted plan as a GitHub issue
   comment on the same issue. If the agent has no GitHub write access, it must
   return the exact comment body for the human to paste.

### High-Reasoning Planning Prompt

```text
Prepare GitHub issue #<number> for multi-agent implementation.

Output must be token-efficient and execution-oriented:
1. Scope: one paragraph.
2. Required first reads: exact files only.
3. Dependency order: numbered.
4. Safety/API evidence requirements.
5. Slice queue:
   - slice id
   - status: pending, in-progress, done, blocked
   - agent class: low-reasoning or high-reasoning
   - objective
   - files to inspect
   - files likely to edit
   - commands/checks
   - stop conditions
6. PR strategy: one PR or multiple PRs.
7. GitHub field updates needed.

Do not implement. Do not broaden scope beyond the issue.

Save the final plan as a GitHub issue comment on issue #<number> with heading:
"Implementation Plan And Slice Queue". If an earlier comment with that heading
exists, update that comment instead of adding a duplicate. If you cannot write
to GitHub, return the exact comment body and say that it still needs to be
posted.
```

### Required Issue Comment Location And Format

The durable plan must be stored as a GitHub issue comment on the roadmap issue
being executed. Do not store it only in chat, scratch files, or a local IDE
session. Use this format so agents can self-serve:

```text
Implementation Plan And Slice Queue

Issue: #<number>
Planner: <agent or human name>
Date: <YYYY-MM-DD>

Scope:
<one paragraph>

Required first reads:
- <exact file>

Dependency order:
1. <dependency>

Safety/API evidence:
- <requirement or known limit>

Slice queue:
- Slice: <id>
  Status: pending
  Agent class: <low-reasoning | high-reasoning>
  Objective: <one sentence>
  Files to inspect: <exact files>
  Files likely to edit: <exact files or none>
  Commands/checks: <commands>
  Stop conditions: <conditions>

PR strategy:
<one PR or multiple PRs>

GitHub field updates:
<labels, milestone, Project #7 `Status`, `Roadmap Lane`, `Priority`, `Safety`,
and PM-field changes>

Rules for agents:
- Take the first unclaimed slice.
- Comment "Claiming slice <id>" before work.
- Update the slice status in this comment or add a progress comment when
  status changes to in-progress, done, or blocked.
- Work only on that slice.
- Stop if safety, API evidence, rollback, readback, or target selection is
  unclear.
- Open a PR titled "<slice id>: <short objective>".
- Link the PR back to this issue.
```

### Low-Reasoning Agent Prompt

```text
Claim and execute the first unclaimed low-reasoning slice in issue #<number>.

Constraints:
- Use only the slice instructions and listed files unless blocked.
- Do not redesign the feature.
- Do not change FL Studio state.
- Keep the diff narrow.
- Run the slice checks.
- Open or prepare one PR and report exact verification.
```

### High-Reasoning Agent Prompt For Complex Slices

```text
Claim and execute the first unclaimed high-reasoning slice in issue #<number>.

Focus:
- Resolve architecture, safety, API-evidence, or cross-module questions.
- Preserve rollback-first behavior.
- Produce a narrow implementation or a documented block with evidence.
- Update the issue with the next executable slice if the plan changes.
```

### Completion Criteria

- All slices are closed, merged, or explicitly blocked in the issue.
- Project #7 `Status` and `Roadmap Lane` reflect reality.
- Snapshot docs are updated through the GitHub snapshot workflow when needed.

## Use Case 3: User Reports A Bug And An Agent Fixes It

### Human/User Actions

1. Open a Bug Report issue.
2. Include FL Studio build, controller marker, OS, Python version, bridge type,
   ping/status evidence, repro steps, and logs.
3. Set labels such as `type:fix`, `area:*`, `read-only`,
   `write-safe-required`, or `api-dependent`.

### Triage Prompt

```text
Triage GitHub bug issue #<number>.

Tasks:
- Classify as reproducible, needs-info, duplicate, expected API limitation, or
  real defect.
- Identify the smallest affected surface.
- List exact files/tests to inspect.
- State whether live FL verification is required.
- If live verification is required, propose read-only first, then rollback-safe
  probe steps.
- Do not implement yet unless the fix is obvious and isolated.
```

### Fix Agent Prompt

```text
Fix GitHub bug issue #<number>.

Rules:
- Read AGENTS.md, agent-docs/engineering/standards.md, agent-docs/project/ROADMAP.github.md,
  and the issue.
- Reproduce or explain why reproduction is impossible.
- Keep the fix minimal and scoped to the bug.
- Do not weaken safety or rollback behavior.
- Add or update focused tests if the behavior is testable offline.
- Update Knowledgebase/API audit/known pitfalls if the bug exposes missing
  reusable knowledge.
- Run focused checks and report verification.
```

### Completion Criteria

- Bug cause is documented in the PR.
- Fix is covered by focused tests or a justified verification path.
- Issue is closed only after the PR is merged or the report is rejected with
  evidence.

## Use Case 4: GitHub Security Features Report A Problem

Security reports may come from CodeQL, Dependabot, secret scanning, or private
vulnerability reporting.

### Human Actions

1. Do not paste secrets or private vulnerability details into public issues.
2. For Dependabot or CodeQL alerts, use the generated alert/PR as source data.
3. For private vulnerability reports, keep discussion inside GitHub Security
   Advisories or private maintainer channels.
4. Decide whether the fix is urgent enough for an immediate branch or can wait
   for the normal milestone.

### Security Agent Prompt

```text
Review the GitHub security alert/PR for thunderdew-dawn/fls-pilot.

Rules:
- Do not expose secrets, private paths, or vulnerability details in public text.
- Identify alert source: CodeQL, Dependabot, secret scanning, or private report.
- Confirm affected files and package versions.
- Propose the smallest safe remediation.
- Check whether the fix changes FL Studio write behavior, file IO, generated
  artifacts, or GitHub Actions permissions.
- If implementation is approved, make one narrow PR and run focused checks.
```

### Completion Criteria

- Alert is closed, dismissed with documented reason, or linked to a merged fix.
- CI/CodeQL are green.
- Any dependency update has a Release Dry Run if packaging could be affected.

## Use Case 5: User Requests A Feature, Human Approves, Agents Plan And Execute

### Human Decision Flow

1. User opens Feature Request or Workflow Request.
2. Human owner decides:
   - accepted
   - needs more evidence
   - duplicate
   - rejected/not planned
3. If accepted, set labels, milestone, `Roadmap Lane`, `Priority`, `Safety`,
   and any relevant PM fields.
4. If rejected, close as not planned with a clear safety/product reason.
5. If evidence is missing, create or link an API Probe issue.

### Approval Comment Template

```text
Decision: accepted

Scope:
- <what is included>

Out of scope:
- <what must not be implemented>

Safety:
- <Read-only | Write-safe required | API-dependent | Mixed/manual>

Planning fields:
- Status: <Todo/Next/In progress/Done>
- Priority: <P0/P1/P2/P3>
- Milestone: <milestone>
- Roadmap Lane: <Now/Next/Later/Blocked/Done>
- Area: <Safety/Workflow/Docs/GitHub/KB/UX/API>
- Type: <Roadmap/Workflow/Doctor/Report/GitHub Sync>
- PM Track: <Safety/Setup/Review/Preflight/Organizer/Governance/Research/Release/none>
- Risk: <Low/Medium/High/API-dependent/none>
- Effort: <number or none>
- PM Iteration: <configured iteration or none>
- Blocked by: <blocking issue, dependency, short reason, or none>

Next step:
- High-reasoning planning agent should produce an implementation plan and slice
  queue. No implementation before plan approval.
```

### Planning Agent Prompt

```text
Plan implementation for accepted feature issue #<number>.

Output:
- User value and acceptance criteria.
- API evidence and safety class.
- Milestone/iteration/quarter recommendation.
- Dependencies and rollout order.
- Slice queue split into low-reasoning and high-reasoning work.
- Testing and verification plan.
- Docs/Knowledgebase/API audit updates.
- PR and release strategy.

Keep output concise. Do not implement.
```

### Execution Agent Prompt

```text
Execute approved slice <id> for feature issue #<number>.

Rules:
- Follow the approved slice plan.
- Keep the diff narrow.
- Do not expand scope.
- Preserve FL safety contract.
- Update issue/PR with exact verification and remaining risk.
```

### Completion Criteria

- Feature matches the approved scope.
- Project fields and milestone are current.
- Docs and Knowledgebase are updated when behavior or reusable evidence changed.
- CI, CodeQL, safety audits, and focused tests pass.

## Common Maintenance Workflows

These workflows cover recurring software-maintenance work that does not always
start as a new product roadmap item.

### Release Execution

Use this when the release decision has already been made.

Human actions:

1. Confirm the target version, release scope, and whether the release is stable
   or prerelease.
2. Confirm `main` is green: CI, CodeQL, Project Fingerprint, and Release Dry
   Run.
3. Confirm generated snapshots are current or intentionally left unchanged.
4. Create or approve the release tag only after the dry run passes.

Release agent prompt:

```text
Prepare release <version> for thunderdew-dawn/fls-pilot.

Rules:
- Inspect pyproject.toml, README.md, agent-docs/project/ROADMAP.github.md,
  agent-docs/project/CHANGELOG.github.md, .github/workflows/release.yml, and the
  latest GitHub releases.
- Do not change FL Studio state.
- Run Release Dry Run before tagging.
- Verify dist metadata with twine check.
- Confirm controller artifact inclusion.
- Produce the exact tag command, expected GitHub Actions workflow, and rollback
  plan for a bad release.
```

Completion criteria:

- Release Dry Run passes on the release commit.
- Tag-triggered Release workflow succeeds.
- GitHub Release contains wheel, source distribution, and controller artifact.
- Any follow-up issue is created for release defects.

### Existing PR CI Failure

Use this when an already-open PR fails CI, CodeQL, or Release Dry Run.

Agent prompt:

```text
Diagnose failing checks for PR #<number>.

Rules:
- Use gh to inspect check names, failing jobs, and logs.
- Identify the smallest failing command and the first relevant error.
- Do not rewrite the PR broadly.
- Propose a fix plan before editing unless the failure is an obvious typo.
- Run the same focused check locally when possible.
- Push a narrow fix commit to the PR branch.
```

Completion criteria:

- The failing check passes.
- The PR diff still matches the original scope.
- Any pre-existing unrelated failure is called out separately.

### Dependency Or Dependabot PR

Use this for Dependabot PRs or routine dependency updates.

Agent prompt:

```text
Review dependency update PR #<number>.

Rules:
- Identify package/ecosystem, old version, new version, and changelog risk.
- Check whether the update touches runtime, dev tooling, GitHub Actions, audio
  dependencies, or packaging.
- Run focused tests plus Release Dry Run when packaging or build behavior might
  change.
- Do not bundle unrelated dependency upgrades.
- If the dependency has a security alert, keep sensitive details out of public
  issue text.
```

Completion criteria:

- CI passes.
- Release Dry Run passes when relevant.
- Security/dependency alert is resolved or explicitly dismissed with reason.
- PR is merged or closed with evidence.

### Review-Only Work

Use this when the user asks for a review without implementation.

Agent prompt:

```text
Review PR #<number> without making code changes.

Rules:
- Prioritize bugs, regressions, safety gaps, missing tests, and API-evidence
  problems.
- Cite file/line references.
- Do not suggest broad refactors unless they block correctness or safety.
- If no issues are found, say so and list residual test or verification gaps.
```

Completion criteria:

- Findings are actionable and ordered by severity.
- Review does not modify files.
- Any required follow-up is assigned to an issue or PR comment.

### Hotfix Or Emergency Fix

Use this for urgent defects that block users, CI, release, install, or safety.

Human actions:

1. Create or identify the hotfix issue.
2. Mark priority and safety labels.
3. Decide whether normal PR review can be shortened.

Hotfix agent prompt:

```text
Implement hotfix for issue #<number>.

Rules:
- Keep the fix as small as possible.
- Avoid unrelated cleanup.
- Preserve rollback and safety contracts.
- Run the narrow failing check, then CI-equivalent checks if practical.
- Document what follow-up cleanup is intentionally deferred.
```

Completion criteria:

- The blocking failure is fixed.
- Required checks pass.
- Follow-up issue exists for non-urgent cleanup.
- Project fields reflect the emergency status and resolution.

### Revert Or Rollback A Bad Change

Use this when a merged change caused a regression or unsafe behavior.

Human actions:

1. Identify the bad commit or PR.
2. Decide whether to revert the whole PR or apply a targeted corrective patch.
3. Open or update an issue with the regression evidence.

Agent prompt:

```text
Prepare rollback for bad change <commit-or-pr>.

Rules:
- Do not use destructive git commands.
- Inspect the original PR, changed files, and current main.
- Prefer `git revert` for a clean whole-PR rollback when appropriate.
- If a targeted patch is safer, explain why.
- Preserve unrelated user changes.
- Run the checks that would have caught the regression.
```

Completion criteria:

- Regression is removed or safely mitigated.
- Revert/corrective PR references the bad change and the regression issue.
- Follow-up issue exists if the root cause still needs analysis.

### Documentation-Only Change

Use this for docs, playbooks, prompts, README updates, or generated snapshots
that do not change runtime behavior.

Agent prompt:

```text
Make documentation-only change for issue/request <number-or-description>.

Rules:
- Keep the diff limited to docs or GitHub metadata.
- Do not change runtime code, tests, controller files, or generated artifacts
  unless explicitly requested.
- Preserve source-of-truth rules: GitHub issues/project for planning,
  generated snapshots for roadmap/changelog views.
- Run markdown-adjacent checks available in the repo and anti-vibe audit.
```

Completion criteria:

- Docs answer the user workflow clearly.
- Links resolve to existing files or GitHub resources.
- CI and CodeQL pass on the PR.

### API Or Compatibility Probe

Use this when behavior depends on FL Studio version, controller marker, target
selection, indexing, readback timing, or undocumented API behavior.

Human actions:

1. Open an API Probe or FL Build Compatibility issue.
2. Include FL Studio build, controller marker, OS, bridge type, target state,
   and exact question.
3. Choose `read-only`, `rollback-safe temporary write`, or `probe-only design
   needed`.

Probe agent prompt:

```text
Plan API/compatibility probe for issue #<number>.

Rules:
- Check Knowledgebase first.
- Do not guess ranges, indices, IDs, or target selection.
- Prefer read-only evidence first.
- If a write is required, define snapshot, smallest write, readback, changelog,
  and rollback before execution.
- Store reusable findings in Knowledgebase and agent-docs/concepts/api-capability-audit.md
  when confirmed.
```

Completion criteria:

- Probe result has confidence level and reproduction steps.
- Knowledgebase is updated when reusable behavior was learned.
- User-facing tools are updated only after evidence and rollback requirements
  are satisfied.

### Backport Or Cherry-Pick

Use this when a fix must be applied to another branch, fork, or sister project.

Human actions:

1. Identify target branch/repo and source commit/PR.
2. Confirm whether behavior, API support, and safety requirements are identical
   in the target.
3. Decide whether the backport should preserve the original commit or become a
   tailored patch.

Backport agent prompt:

```text
Backport <commit-or-pr> to <target-branch-or-repo>.

Rules:
- Inspect the source change and target branch state.
- Do not assume APIs, paths, or safety helpers are identical.
- Prefer a clean cherry-pick only when dependencies match.
- If conflicts occur, resolve narrowly and document target-specific changes.
- Run target-branch checks, not only source-branch checks.
```

Completion criteria:

- Target branch/repo has a focused PR or commit.
- Checks pass in the target context.
- Any skipped part of the source change is documented with reason.

## Recommended GitHub Commands

```bash
gh issue view <number> --repo thunderdew-dawn/fls-pilot
gh project item-list 7 --owner thunderdew-dawn --limit 100 --format json
python3 scripts/check_github_project_fingerprint.py
gh run list --repo thunderdew-dawn/fls-pilot --limit 10
gh workflow run project_fingerprint.yml --repo thunderdew-dawn/fls-pilot --ref main
gh workflow run roadmap_changelog_sync.yml --repo thunderdew-dawn/fls-pilot --ref main -f write_canonical=false
gh workflow run release_dry_run.yml --repo thunderdew-dawn/fls-pilot --ref main
```

## Stop Conditions

Agents must stop and ask for human decision when:

- the requested behavior conflicts with `AGENTS.md` or
  `agent-docs/engineering/standards.md`;
- FL Studio API support, target selection, rollback, readback, or value ranges
  are unclear;
- implementation would require prohibited automation;
- a low-reasoning slice discovers architectural ambiguity;
- a security alert involves private vulnerability details or secrets;
- Project #7 fingerprint fails and the issue/project state cannot be explained.
