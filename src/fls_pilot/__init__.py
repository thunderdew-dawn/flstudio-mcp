"""fls-pilot -- MCP server that controls FL Studio via a MIDI SysEx bridge."""

from __future__ import annotations

__version__ = "3.0.0b3"

from .connection import (
    FLBridge,
    FLBridgeError,
    FLCommandFailed,
    FLNotRunning,
    FLPortMissing,
    FLTimeout,
    fetch_all_pages,
    get_bridge,
    list_ports,
    reset_bridge,
)
from .protocol import (
    PROTOCOL_VERSION,
    port_from_fl_name,
    port_to_fl_name,
)

__all__ = [
    "__version__",
    "FLBridge",
    "FLBridgeError",
    "FLCommandFailed",
    "FLNotRunning",
    "FLPortMissing",
    "FLTimeout",
    "fetch_all_pages",
    "get_bridge",
    "list_ports",
    "reset_bridge",
    "PROTOCOL_VERSION",
    "port_to_fl_name",
    "port_from_fl_name",
]
