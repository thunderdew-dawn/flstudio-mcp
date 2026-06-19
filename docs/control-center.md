
![fls-pilot logo](assets/fls-pilot-logo-with-title-and-slogan.png)
# Control Center

The Control Center is the recommended first-run and daily runtime surface for
fls-pilot. It opens locally, keeps setup checks read-only against the FL Studio
project, and shows the ports and MCP snippets your client should use.

![Control Center setup overview](assets/control-center-setup-overview.png)

## Guided Setup

Use the guided setup before connecting an MCP client or starting write-capable
workflows. It checks Python, dependencies, whether FL Studio is running,
virtual MIDI ports, the FL Studio controller heartbeat, daemon status, SSE
status, and the Piano Roll script bridge separately.

![Control Center setup doctor](assets/control-center-setup-doctor.png)

The checks are intentionally separated and ordered. Setup Doctor and Control
Center distinguish between three distinct states:

1. **FL Studio is not running** — the "Open FL Studio" action is shown first.
   The controller script check is skipped until FL Studio is open, so a missing
   heartbeat is never mistaken for a controller configuration problem.
2. **FL Studio is running but the controller is not connected** — the controller
   and heartbeat checks run and report the actual issue.
3. **Bridge or MIDI is not reachable** — reported as a separate finding.

A working MCP server does not prove that FL Studio is connected, and a running
daemon does not prove that the controller script is receiving MIDI.

## Dynamic Ports

Default local ports are Control Center `8766`, ChatGPT/SSE `8080`, and daemon
`9787`. If a port is busy, Control Center chooses a fallback and updates the
displayed URL and client snippets.

![Control Center dynamic ports](assets/control-center-dynamic-used-ports-view.png)

## Project Review Panels

After setup, Control Center provides read-only review panels for common
production checks.

![Project health status](assets/control-center-flstudio-project-health-status.png)

Mix Review and Low-End Analysis help find headroom, clipping, bass, and stereo
risks before any edit is proposed.

![Mix Review panel](assets/control-center-mix-review-1.png)

![Low-end analysis panel](assets/control-center-low-end-analysis-1.png)

Routing Audit and Organizer focus on structure: route health, bus layout,
names, colors, and cleanup candidates.

![Routing Audit panel](assets/control-center-routing-audit.png)

![Project Organizer panel](assets/control-center-project-organizer.png)
