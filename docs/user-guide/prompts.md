![fls-pilot logo](../assets/fls-pilot-logo.svg)
# Prompt Examples

You do not need to know MCP tool names to use fls-pilot. Start with intent and state whether the assistant may change the project.

## Read-Only First

!!! tip "Read-Only Workflows"
    These prompts will not change your project. They rely on the observation tools and analysis workflows.

```text
Scan my mix first. Do not change anything yet. Report the top three risks and the safest next action.
```

```text
Review my routing and bus structure. Give me a read-only diagnosis and one rollback-safe cleanup proposal.
```

```text
Prepare this project for export. Report blockers first and use dry-run planning only.
```

## Approved One-Step Changes

!!! warning "Requires Approval"
    These prompts instruct the agent to make changes. Always ask the agent to propose the change first and wait for your confirmation.

```text
Rename mixer track 8 to Lead Vocal, verify the result, and show me the rollback ID.
```

```text
Apply the one gain-staging fix you proposed. Make only that change, read it back, then stop.
```

```text
Color the drum tracks using the standard project colors. Propose the exact change first and wait for my confirmation.
```

## Composition

!!! note "Piano Roll Bridge Required"
    Composition tools require the Piano Roll bridge to be armed. Ensure you have run `MCP_Apply` from the Piano Roll script menu.

```text
Prepare an 8-bar D Dorian bassline for the selected channel. Preview the notes first and wait for confirmation before writing to the Piano Roll.
```

```text
Generate a chord progression in A minor, but do not write it until I approve the exact voicing.
```

## Plugin and EQ Work

!!! important "Supported Plugins Only"
    Plugin parameter automation is limited to natively supported plugins or safely mapped parameters.

```text
Find the EQ on the lead vocal and propose one rollback-safe harshness reduction around 3 kHz. Wait for confirmation before changing it.
```

```text
Suggest a warm bass chain from my installed plugins. If a plugin is not loaded, give me manual steps instead of trying to load it.
```

## Recovery

!!! tip "Rollback-backed"
    Most state changes made by fls-pilot can be cleanly rolled back. Ask the agent to restore the previous state if something goes wrong.

```text
Show the recent fls-pilot change history.
```

```text
Rollback the last MCP change and report what was restored.
```
