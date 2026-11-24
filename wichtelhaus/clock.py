"""Uhr: echte Zeit oder Zeitraffer für den Simulationsmodus."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional


class Clock:
    """Liefert die aktuelle Zeit in der Zeitzone des Hauses.

    Ohne Startzeit und mit speed=1 ist das die echte Uhrzeit. Sonst läuft eine
    simulierte Uhr ab ``start`` mit ``speed``-facher Geschwindigkeit. Intern wird
    in UTC gerechnet, damit Sommer-/Winterzeitwechsel keine Sprünge machen.
    """

    def __init__(self, tz: tzinfo, start: Optional[datetime] = None, speed: float = 1.0):
        self.tz = tz
        self.speed = float(speed)
        self.simulated = start is not None or self.speed != 1.0
        base = start or datetime.now(tz)
        self._start_utc = base.astimezone(timezone.utc)
        self._t0 = time.monotonic()

    def now(self) -> datetime:
        if not self.simulated:
            return datetime.now(self.tz)
        elapsed = (time.monotonic() - self._t0) * self.speed
        return (self._start_utc + timedelta(seconds=elapsed)).astimezone(self.tz)
