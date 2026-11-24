"""Sonnenauf- und -untergang für den echten Standort (astral)."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Optional

from astral import Observer
from astral.sun import sun

log = logging.getLogger(__name__)


class SunTimes:
    def __init__(self, latitude: float, longitude: float, tz: tzinfo):
        self.observer = Observer(latitude=latitude, longitude=longitude)
        self.tz = tz
        self._cache: dict[date, tuple[datetime, datetime]] = {}

    def get(self, day: date) -> tuple[datetime, datetime]:
        """(Sonnenaufgang, Sonnenuntergang) für einen Tag, in lokaler Zeit."""
        times = self._cache.get(day)
        if times is None:
            try:
                s = sun(self.observer, date=day, tzinfo=self.tz)
                times = (s["sunrise"], s["sunset"])
            except ValueError as exc:  # nur in Polargebieten möglich
                log.warning("Sonnenzeiten für %s nicht berechenbar (%s), nehme 08:00/16:00", day, exc)
                times = (
                    datetime.combine(day, time(8, 0), tzinfo=self.tz),
                    datetime.combine(day, time(16, 0), tzinfo=self.tz),
                )
            if len(self._cache) > 8:
                self._cache.clear()
            self._cache[day] = times
        return times

    def is_dark(self, now: datetime, before_sunset_min: float = 0, after_sunrise_min: float = 0) -> bool:
        """Dunkel = vor (Sonnenaufgang + Puffer) oder nach (Sonnenuntergang - Puffer)."""
        sunrise, sunset = self.get(now.date())
        light_from = sunrise + timedelta(minutes=after_sunrise_min)
        light_until = sunset - timedelta(minutes=before_sunset_min)
        return not (light_from <= now < light_until)

    def outside_light_on(self, now: datetime, off_at: Optional[time] = None) -> bool:
        """Außenlicht: an ab Sonnenuntergang bis Sonnenaufgang oder bis ``off_at``."""
        today = now.date()
        for day in (today, today - timedelta(days=1)):
            _, sunset = self.get(day)
            next_sunrise, _ = self.get(day + timedelta(days=1))
            if off_at is None:
                end = next_sunrise
            else:
                end = datetime.combine(day, off_at, tzinfo=self.tz)
                if end <= sunset:  # z. B. 01:00 -> gehört zur Nacht danach
                    end += timedelta(days=1)
                end = min(end, next_sunrise)
            if sunset <= now < end:
                return True
        return False
