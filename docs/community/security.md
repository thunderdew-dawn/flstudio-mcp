# Security Policy

## Supported Versions

Security fixes target the maintained `main` branch and the latest tagged
release line.

## Reporting A Vulnerability

Please report security issues privately through GitHub Private Vulnerability Reporting.
If that is not available, contact <fls-pilot@posteo.org>.

Do not open public issues for vulnerabilities that could expose user systems,
local file paths, credentials, MIDI bridge state, or unsafe host-automation
behavior.

## Project Boundaries

This project controls a local DAW through FL Studio scripting APIs. Security and
safety reports are especially useful when they involve:

- Unsafe FL Studio state mutation without rollback.
- Raw API escape hatches or broad UI automation.
- Path traversal, unintended file writes, or unsafe generated artifacts.
- Secrets, tokens, or local user data being logged or exposed.
- Dependency or GitHub Actions supply-chain risk.

The project does not support plugin loading/insertion, project open/save/render
automation, playlist clip editing, destructive pattern/clip deletion, or full
FLP snapshot/restore claims.

## Expected Response

Maintainers will triage reports as soon as practical, ask for reproduction
details if needed, and coordinate a fix or mitigation before public disclosure.
