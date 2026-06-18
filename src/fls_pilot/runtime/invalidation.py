"""Map verified writes to conservative Runtime evidence invalidation."""

from __future__ import annotations

from typing import Any

from ..connection import TCPBridge
from .client import RuntimeClient


def event_for_write(*, scope: str, command: str | None = None) -> str:
    normalized = str(scope or "").lower()
    if "routing" in normalized or "route" in str(command or "").lower():
        return "routing_change"
    if normalized.startswith("channel"):
        return "channel_structure_change"
    if normalized.startswith(("mixer", "effect", "plugin")):
        return "mixer_structure_change"
    if normalized.startswith(("pattern", "playlist", "piano")):
        return "project_structure_change"
    return "project_state_change"


def notify_verified_write(
    bridge: Any,
    *,
    scope: str,
    command: str | None = None,
) -> None:
    """Notify only daemon-backed Runtime sessions; direct test bridges are inert."""
    if not isinstance(bridge, TCPBridge):
        return
    RuntimeClient(
        host=bridge.host,
        port=bridge.port,
        timeout=bridge.default_timeout + 5.0,
    ).request(
        "runtime.invalidate",
        {"event": event_for_write(scope=scope, command=command)},
    )
