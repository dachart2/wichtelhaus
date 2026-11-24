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

    def outside_light_on(
        self,
        now: datetime,
        off_at: Optional[time] = None,
        season: Optional[tuple[tuple[int, int], tuple[int, int]]] = None,
    ) -> bool:
        """Außenlicht: an ab Sonnenuntergang bis Sonnenaufgang oder bis ``off_at``.

        season: ((Monat, Tag), (Monat, Tag)) – nur Abende in diesem Zeitraum
        (inklusive, darf über den Jahreswechsel gehen). None = ganzjährig.
        """
        today = now.date()
        for day in (today, today - timedelta(days=1)):
            if season is not None and not in_season(day, season):
                continue
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


def parse_month_day(value: str) -> tuple[int, int]:
    """'TT.MM.' oder 'TT.MM' -> (Monat, Tag)"""
    parts = [p for p in str(value).strip().split(".") if p]
    if len(parts) != 2:
        raise ValueError(f"'{value}' bitte als TT.MM. angeben, z. B. 01.12.")
    day, month = int(parts[0]), int(parts[1])
    date(2024, month, day)  # prüft, ob es den Tag gibt (2024 = Schaltjahr)
    return month, day


def in_season(day: date, season: tuple[tuple[int, int], tuple[int, int]]) -> bool:
    start, end = season
    md = (day.month, day.day)
    if start <= end:
        return start <= md <= end
    return md >= start or md <= end  # z. B. 15.12. bis 06.01.
