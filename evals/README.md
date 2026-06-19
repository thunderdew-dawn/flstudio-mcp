# FLStudioPilot Evaluations

**Source changes define implementation behavior; evals preserve expected agent behavior.**

`evals/evals.json` is treated as a prompt/tool-surface contract, not loose test data.

Whenever a pull request changes what a user can ask, which MCP tool an agent should choose, what safety boundaries apply, what workflows are exposed, or what capabilities are publicly asserted, the evals must be reviewed.

Changes that usually require an eval update include:

- new, renamed, or removed MCP tools;
- changes to workflow logic;
- changes to safety, approval, rollback, or readback behavior;
- changes to capability registry entries;
- changes to prompt or resource templates;
- changes to known public API limits;
- changes to user-facing agent expectations.

For each relevant PR, either update `evals/evals.json` or explicitly justify in the PR body why the existing evals remain valid.

The contract check is enforced by `scripts/check_evals_contract.py`.

The public MCP tool surface is derived from the live MCP registry in the Python codebase. Evals must not reference stale or removed tool names.
