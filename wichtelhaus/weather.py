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
        if self.fixed:
            self._temp = float(fixed)
        else:
            self._load_cache()

    @property
    def temperature(self) -> Optional[float]:
        with self._lock:
            return self._temp

    def describe(self) -> str:
        temp = self.temperature
        if temp is None:
            return "unbekannt"
        if self.fixed:
            return f"{temp:.1f} °C (fest vorgegeben)"
        with self._lock:
            updated = self._updated
        age = "" if updated is None else f", vor {int((time.time() - updated) / 60)} min"
        return f"{temp:.1f} °C{age}"

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
                    "current": "temperature_2m",
                    "timezone": "auto",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            temp = float(response.json()["current"]["temperature_2m"])
        except Exception as exc:  # Netz weg, Server-Fehler, kaputtes JSON …
            log.warning("Temperatur nicht abrufbar (%s), verwende letzten Wert: %s", exc, self.describe())
            return False
        with self._lock:
            changed = self._temp is None or abs(self._temp - temp) >= 0.05
            self._temp = temp
            self._updated = time.time()
        if changed:
            log.info("Außentemperatur: %.1f °C", temp)
        self._save_cache()
        return True

    def _load_cache(self) -> None:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self._temp = float(data["temperatur"])
            self._updated = float(data["zeit"])
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
                data = {"temperatur": self._temp, "zeit": self._updated}
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self.cache_path)
        except OSError as exc:
            log.warning("Temperatur konnte nicht gespeichert werden: %s", exc)
