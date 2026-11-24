"""config.yaml laden, mit Standardwerten zusammenführen und prüfen."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .wichtel import ROOMS, parse_hhmm

DEFAULTS: dict[str, Any] = {
    "standort": {
        "name": "Zillingdorf-Bergwerk",
        "breite": 47.86,
        "laenge": 16.32,
        "zeitzone": "Europe/Vienna",
    },
    "leds": {
        "pin": 18,
        "anzahl": 56,
        "pixel_order": "GRB",
        "max_helligkeit": 0.1,
        "farbe": [255, 147, 41],
        "raumhelligkeit": 1.0,
        "grundhelligkeit": 0.25,
        "nachtlicht": 0.12,
        "fade_sekunden": 90,
        "einschlaf_fade_sekunden": 900,
        "zonen": {
            "kueche": [0, 13],
            "wohnbereich": [14, 27],
            "arbeitsecke": [28, 41],
            "schlafbereich": [42, 55],
        },
        "raeume": {
            "kueche": "kueche",
            "wohnbereich": "wohnbereich",
            "fenster": "wohnbereich",
            "arbeitsecke": "arbeitsecke",
            "schlafbereich": "schlafbereich",
        },
    },
    "dunkel": {"vor_sonnenuntergang_min": 30, "nach_sonnenaufgang_min": 30},
    "ofen": {
        "aktiv": True,
        "pixel": [0, 1, 2, 3],
        "nur_ofen": True,
        "temperatur_grenze": 5.0,
        "helligkeit": 0.9,
        "glut_minuten": 60,
        "glut_helligkeit": 0.3,
    },
    "wetter": {"intervall_minuten": 20, "timeout_sekunden": 10, "cache_datei": "state/temperatur.json"},
    "aussenlicht": {"aktiv": True, "pin": 21, "active_low": True, "aus_um": None},
    "laterne": {"aktiv": True, "pin": 20, "active_low": True, "aus_um": None},
    "wichtel": {
        "aufwachen": ["06:00", "09:00"],
        "schlafen": ["20:00", "23:00"],
        "nachts_aufstehen": 0.5,
        "ausflug_chance": 0.015,
    },
}

REPLACE_WHOLE = {"zonen", "raeume"}  # werden nicht gemischt, sondern ersetzt


def _merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict) and key not in REPLACE_WHOLE:
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | str) -> dict:
    path = Path(path)
    with path.open(encoding="utf-8") as fh:
        user = yaml.safe_load(fh) or {}
    if not isinstance(user, dict):
        raise ValueError(f"{path} muss ein YAML-Wörterbuch enthalten")
    cfg = _merge(DEFAULTS, user)
    validate(cfg)
    cache = Path(cfg["wetter"]["cache_datei"])
    cfg["_cache_path"] = cache if cache.is_absolute() else path.parent / cache
    return cfg


def validate(cfg: dict) -> None:
    def check(cond: bool, msg: str) -> None:
        if not cond:
            raise ValueError(msg)

    ZoneInfo(cfg["standort"]["zeitzone"])  # wirft bei Tippfehlern
    check(-90 <= float(cfg["standort"]["breite"]) <= 90, "standort.breite muss zwischen -90 und 90 liegen")
    check(-180 <= float(cfg["standort"]["laenge"]) <= 180, "standort.laenge muss zwischen -180 und 180 liegen")

    leds = cfg["leds"]
    n = int(leds["anzahl"])
    check(n > 0, "leds.anzahl muss größer als 0 sein")
    check(0 < float(leds["max_helligkeit"]) <= 1, "leds.max_helligkeit muss zwischen 0 und 1 liegen")
    check(len(leds["farbe"]) == 3 and all(0 <= int(c) <= 255 for c in leds["farbe"]), "leds.farbe: [R, G, B] mit 0–255")
    for key in ("raumhelligkeit", "grundhelligkeit", "nachtlicht"):
        check(0 <= float(leds[key]) <= 1, f"leds.{key} muss zwischen 0 und 1 liegen")
    for key in ("fade_sekunden", "einschlaf_fade_sekunden"):
        check(float(leds[key]) >= 1, f"leds.{key} muss mindestens 1 sein")
    check(bool(leds["zonen"]), "leds.zonen darf nicht leer sein")
    for name, span in leds["zonen"].items():
        check(
            isinstance(span, list) and len(span) == 2 and 0 <= int(span[0]) <= int(span[1]) < n,
            f"leds.zonen.{name}: [erste, letzte] LED, beide zwischen 0 und {n - 1}",
        )
    for room, zone in leds["raeume"].items():
        check(room in ROOMS, f"leds.raeume: unbekannter Raum '{room}' (erlaubt: {', '.join(ROOMS)})")
        check(zone in leds["zonen"], f"leds.raeume.{room}: Zone '{zone}' gibt es nicht in leds.zonen")

    oven = cfg["ofen"]
    for i in oven["pixel"]:
        check(0 <= int(i) < n, f"ofen.pixel: LED {i} liegt außerhalb von 0–{n - 1}")
    check(float(oven["glut_minuten"]) > 0, "ofen.glut_minuten muss größer als 0 sein")

    check(float(cfg["wetter"]["intervall_minuten"]) >= 5, "wetter.intervall_minuten: bitte mindestens 5")

    for key in ("aussenlicht", "laterne"):
        if cfg[key]["aus_um"] is not None:
            parse_hhmm(cfg[key]["aus_um"])
    if cfg["aussenlicht"]["aktiv"] and cfg["laterne"]["aktiv"]:
        check(int(cfg["aussenlicht"]["pin"]) != int(cfg["laterne"]["pin"]), "aussenlicht und laterne brauchen verschiedene Pins")

    w = cfg["wichtel"]
    for key in ("aufwachen", "schlafen"):
        check(len(w[key]) == 2, f"wichtel.{key}: [von, bis]")
        start, end = (parse_hhmm(x) for x in w[key])
        check(start < end, f"wichtel.{key}: 'von' muss vor 'bis' liegen (am selben Tag)")
    check(parse_hhmm(w["aufwachen"][1]) < parse_hhmm(w["schlafen"][0]), "wichtel: Aufwachen muss vor Schlafengehen liegen")
