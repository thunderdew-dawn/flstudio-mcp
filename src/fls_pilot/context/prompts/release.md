# Release Prompt

Use this when the release decision has already been made.

```text
Prepare release <version> for thunderdew-dawn/fls-pilot.

Rules:
- Read AGENTS.md, agent-docs/agents/github-playbook.md, agent-docs/agents/development.md,
  agent-docs/engineering/standards.md, agent-docs/project/ROADMAP.github.md, and the latest
  GitHub releases.
- Inspect pyproject.toml, README.md, agent-docs/project/ROADMAP.github.md,
  agent-docs/project/CHANGELOG.github.md, .github/workflows/release.yml, and
  release-related workflows.
- Do not change FL Studio state.
- Run Release Dry Run before tagging.
- Verify dist metadata with twine check.
- Confirm controller artifact inclusion.
- Produce the exact tag command, expected GitHub Actions workflow, and rollback
  plan for a bad release.
```
