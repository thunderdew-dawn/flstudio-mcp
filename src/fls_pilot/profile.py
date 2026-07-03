"""Optional JSON timing profiler hooks.

Enable by setting ``FLS_PILOT_PROFILE=1`` (or ``true``, ``yes``, ``on``).
The profiler only emits when enabled and is intentionally lightweight.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from collections.abc import Iterator
from typing import Any


logger = logging.getLogger("fls_pilot.profile")


def _is_enabled() -> bool:
    raw = os.environ.get("FLS_PILOT_PROFILE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@contextlib.contextmanager
def profile(operation: str, **fields: Any) -> Iterator[None]:
    """Profile a scoped operation and emit JSON timing when profiling is enabled."""
    if not _is_enabled():
        yield
        return

    start = time.perf_counter()
    status = "ok"
    exc_name = None
    try:
        yield
    except Exception as exc:
        status = "error"
        exc_name = type(exc).__name__
        raise
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000.0, 3)
        payload = {
            "event": "fls_pilot.profile",
            "operation": operation,
            "status": status,
            "duration_ms": duration_ms,
            **fields,
        }
        if exc_name is not None:
            payload["error"] = exc_name
        logger.debug(json.dumps(payload, default=str))
