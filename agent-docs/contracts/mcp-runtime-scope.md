# MCP Runtime Scope Contract

This contract governs agents that use FLStudioPilot with a live FL Studio
session.

## Core Rule

Runtime/MCP Usage Mode is tool-first, resource-first, and repo-last.

Current runtime evidence comes from MCP resources and tools. Static repository
source can explain implementation, but it cannot prove current bridge health,
project state, transport state, routing, mixer values, plugins, patterns, or
any other live FL Studio fact.

## Required Runtime Path

1. Start with `fl://agent-briefing` and `fl://status` when available.
2. Use scoped project/transport/channel/mixer/pattern resources for orientation.
3. Use capability, tool-policy, runtime-usage, safety, and write-safety
   resources as needed.
4. Use Knowledgebase tools before value-dependent FL work.
5. Prefer read-only workflow/domain tools.
6. For persistent writes, follow proposal, explicit approval, scoped write,
   readback, changelog, rollback, and stop.

## Repository Read Exceptions

Repository files may be read in Runtime/MCP Usage Mode only when:

- The user explicitly asks about repository source, implementation,
  development, debugging, tests, release, CI, security, or architecture.
- An MCP resource points to a specific repository document needed for the
  active task.
- A diagnosis is impossible without repository context and the agent states
  that limitation before expanding scope.

When an exception applies, repository content remains maintenance evidence.
Re-check live claims through MCP.

## Prohibited Inferences

Runtime agents must not:

- Infer live FL Studio state from source, tests, docs, fixtures, or snapshots.
- Claim a command succeeded because a handler exists.
- Treat packaged capability documentation as proof that the current bridge,
  controller build, target, or FL version supports an action.
- Bypass a high-level tool with raw protocol/controller calls.
- Retry an uncertain write as if it were a read.

## Safe Fallback

If live evidence, API support, target selection, readback, or rollback is
unclear:

- Stay read-only.
- Offer a dry-run, proposal, focused probe, or manual instruction.
- Explain the missing evidence.
- Do not claim completion.

Runtime scope ends when the user asks to change repository behavior. At that
point switch to Repository Development Mode and follow `AGENTS.md`.
