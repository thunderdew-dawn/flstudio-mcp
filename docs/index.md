![fls-pilot logo](assets/fls-pilot-logo-with-title-and-slogan.png)

**Create more. Check less.**

fls-pilot connects FL Studio to MCP-compatible AI clients. It gives assistants readable project context, production workflow tools, and rollback-first write paths for supported FL Studio actions.

[Setup Guide](user-guide/setup.md){ .md-button .md-button--primary } [View Workflows](user-guide/workflows.md){ .md-button }

## Safety First

!!! tip "Read-only by Default"
    fls-pilot is intentionally conservative. Read-only checks can run immediately. Persistent FL Studio project writes require explicit approval, scoped state, the smallest practical change, readback where supported, and a rollback path. Unsupported DAW actions are not hidden behind automation claims.

## Example Workflows

[![Mix Review & Gain Staging](assets/ai-apply-gain-staging-example.gif)](assets/ai-apply-gain-staging-example.gif)

[![Routing Audit](assets/ai-based-mixer-routing-example.gif)](assets/ai-based-mixer-routing-example.gif)

[![Project Organizer](assets/ai-color-my-tracks-example.gif)](assets/ai-color-my-tracks-example.gif)

Use it for mix review, routing checks, project organization, Piano Roll composition, plugin-chain planning, audio analysis, MIDI export, and export-readiness checks.

![Project health status](assets/control-center-flstudio-project-health-status.png)

## Why It Exists

AI assistants are useful in a DAW only when they can see real project state and respect the DAW's limits. fls-pilot provides that boundary:

- Live project context through MCP resources and domain tools.
- Knowledgebase-backed ranges and API limits instead of guessed values.
- Proposal-first workflows for changes that could affect a project.
- Rollback-backed writes where FL Studio exposes enough state to restore them.

## Ask Your Agent

```text
Scan my mix first, explain the top three issues, and do not change anything yet.
```

## Next Steps

- [Setup](user-guide/setup.md)
- [Control Center](control-center.md)
- [Workflows](user-guide/workflows.md)
- [Safety & Limits](safety-limits.md)
- [MCP Integration](mcp-integration.md)
