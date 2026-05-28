from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class TimeService:
    """Central clock provider.

    Wall time is for user-facing timestamps. Monotonic time is for elapsed time,
    timeouts, heartbeat, and cooldown logic.
    """

    def wall_ms(self) -> int:
        return int(time.time() * 1000)

    def wall_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def monotonic_ms(self) -> int:
        return int(time.monotonic() * 1000)
