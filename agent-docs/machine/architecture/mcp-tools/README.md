# MCP Tool Module Slices

This directory splits the generated MCP tool inventory by tool module.

For MCP work, load:

1. `agent-docs/machine/architecture-governance.snapshot.json`
2. `agent-docs/machine/architecture/index.snapshot.json`
3. `agent-docs/machine/architecture/mcp-surface.snapshot.json`
4. only the affected file in this directory

Do not load every module slice unless doing a full MCP surface audit.
