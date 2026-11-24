"""Außentemperatur aus dem Internet (Open-Meteo, ohne API-Key), mit Zwischenspeicher."""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

URL = "https://api.open-meteo.com/v1/forecast"
RETRY_SECONDS = 300  # nach einem Fehler früher erneut versuchen
SNOW_CODES = {71, 73, 75, 77, 85, 86}  # WMO-Wettercodes
RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}


class Weather:
    """Holt die Temperatur in einem Hintergrund-Thread.

    Fällt das Internet aus, bleibt der letzte Wert gültig. Er wird in eine Datei
    geschrieben, damit er auch einen Neustart übersteht.
    """

    def __init__(
        self,
        latitude: float,
        longitude: float,
        interval_minutes: float,
        timeout_seconds: float,
        cache_path: Path,
        fixed: Optional[float] = None,
        fixed_code: Optional[int] = None,
    ):
        self.latitude = latitude
        self.longitude = longitude
        self.interval = max(60.0, float(interval_minutes) * 60)
        self.timeout = float(timeout_seconds)
        self.cache_path = Path(cache_path)
        self.fixed = fixed is not None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._temp: Optional[float] = None
        self._updated: Optional[float] = None
        self._code: Optional[int] = fixed_code
        self.fixed_code = fixed_code is not None
        if self.fixed:
            self._temp = float(fixed)
        else:
            self._load_cache()

    @property
    def temperature(self) -> Optional[float]:
        with self._lock:
            return self._temp

    @property
    def code(self) -> Optional[int]:
        with self._lock:
            return self._code

    @property
    def snowing(self) -> bool:
        return self.code in SNOW_CODES

    @property
    def raining(self) -> bool:
        return self.code in RAIN_CODES

    def describe(self) -> str:
        temp = self.temperature
        if temp is None:
            return "unbekannt"
        sky = ", Schnee" if self.snowing else (", Regen" if self.raining else "")
        if self.fixed:
            return f"{temp:.1f} °C{sky} (fest vorgegeben)"
        with self._lock:
            updated = self._updated
        age = "" if updated is None else f", vor {int((time.time() - updated) / 60)} min"
        return f"{temp:.1f} °C{sky}{age}"

    def start(self) -> None:
        if self.fixed or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="wetter", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            ok = self.fetch_once()
            self._stop.wait(self.interval if ok else min(self.interval, RETRY_SECONDS))

    def fetch_once(self) -> bool:
        try:
            response = requests.get(
                URL,
                params={
                    "latitude": self.latitude,
                    "longitude": self.longitude,
                    "current": "temperature_2m,weather_code",
                    "timezone": "auto",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            current = response.json()["current"]
            temp = float(current["temperature_2m"])
            code = current.get("weather_code")
            code = int(code) if code is not None else None
        except Exception as exc:  # Netz weg, Server-Fehler, kaputtes JSON …
            log.warning("Temperatur nicht abrufbar (%s), verwende letzten Wert: %s", exc, self.describe())
            return False
        with self._lock:
            changed = self._temp is None or abs(self._temp - temp) >= 0.05
            self._temp = temp
            self._updated = time.time()
            if not self.fixed_code:
                self._code = code
        if changed:
            log.info("Außentemperatur: %.1f °C", temp)
        self._save_cache()
        return True

    def _load_cache(self) -> None:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self._temp = float(data["temperatur"])
            self._updated = float(data["zeit"])
            if not self.fixed_code and data.get("wettercode") is not None:
                self._code = int(data["wettercode"])
            log.info("Letzte bekannte Temperatur geladen: %s", self.describe())
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.warning("Temperatur-Zwischenspeicher unlesbar (%s), ignoriere ihn", exc)

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            with self._lock:
                data = {"temperatur": self._temp, "zeit": self._updated, "wettercode": self._code}
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self.cache_path)
        except OSError as exc:
            log.warning("Temperatur konnte nicht gespeichert werden: %s", exc)
