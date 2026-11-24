"""Hauptprogramm: verbindet Wichtel, Sonne, Wetter, LEDs, Ofen und Außenlicht."""
from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

import yaml

from . import __version__
from .clock import Clock
from .config import load_config
from .fire import Fire
from .outputs import make_outputs
from .sun import SunTimes
from .weather import Weather
from .wichtel import ROOM_NAMES, Wichtel, parse_hhmm

log = logging.getLogger("wichtelhaus")

TICK_SECONDS = 0.04  # ca. 25 Bilder pro Sekunde fürs Feuer
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"

Color = tuple[int, int, int]


def fmt(now: datetime) -> str:
    return f"{WEEKDAYS[now.weekday()]} {now:%d.%m. %H:%M}"


def approach(current: float, target: float, step: float) -> float:
    if current < target:
        return min(target, current + step)
    return max(target, current - step)


class WichtelHaus:
    def __init__(self, cfg: dict, args: argparse.Namespace):
        self.cfg = cfg
        self.tz = ZoneInfo(cfg["standort"]["zeitzone"])
        start = parse_start(args.start, self.tz) if args.start else None
        self.clock = Clock(self.tz, start=start, speed=args.speed)
        self.sim = args.sim
        self.live = args.live
        self.color = not args.no_color
        self.stop_event = threading.Event()

        st = cfg["standort"]
        self.sun = SunTimes(float(st["breite"]), float(st["laenge"]), self.tz)
        wcfg = cfg["wetter"]
        self.weather = Weather(
            float(st["breite"]),
            float(st["laenge"]),
            wcfg["intervall_minuten"],
            wcfg["timeout_sekunden"],
            cfg["_cache_path"],
            fixed=args.temp,
        )
        self.wichtel = Wichtel(cfg["wichtel"], self.tz, rng=random.Random(args.seed), on_event=self._event)

        leds = cfg["leds"]
        self.n = int(leds["anzahl"])
        self.zones = {name: (int(a), int(b)) for name, (a, b) in leds["zonen"].items()}
        self.levels = dict.fromkeys(self.zones, 0.0)
        oven = cfg["ofen"]
        self.oven_pixels = [int(i) for i in oven["pixel"]] if oven["aktiv"] else []
        self.oven_level = 0.0
        self.fire = Fire(len(self.oven_pixels))
        off_at = cfg["aussenlicht"]["aus_um"]
        self.outside_off_at = parse_hhmm(off_at) if off_at is not None else None
        lantern_off = cfg["laterne"]["aus_um"]
        self.lantern_off_at = parse_hhmm(lantern_off) if lantern_off is not None else None

        self.pixels: list[Color] = [(0, 0, 0)] * self.n
        self.outside_on = False
        self.lantern_on = False
        self._last_modes: Optional[tuple] = None
        self._last_live = 0.0
        self.pixel_out, self.relay_out, self.lantern_out = make_outputs(cfg, sim=args.sim)

    # ------------------------------------------------------------ Hauptschleife
    def run(self, days: Optional[float] = None) -> None:
        self._install_signals()
        self.weather.start()
        now = self.clock.now()
        end = now + timedelta(days=days) if days else None
        self._log_intro(now)

        utc = timezone.utc
        next_min = now.astimezone(utc).replace(second=0, microsecond=0)
        max_lag = timedelta(seconds=max(600.0, self.clock.speed * 2))
        last, real_last = now, time.monotonic()
        try:
            while not self.stop_event.is_set():
                now = self.clock.now()
                if now - next_min > max_lag or next_min - now > timedelta(minutes=2):
                    log.warning("Die Uhr ist gesprungen (auf %s), stelle den Wichtel neu ein", fmt(now))
                    next_min = now.astimezone(utc).replace(second=0, microsecond=0)
                    self.wichtel.resync(next_min.astimezone(self.tz))
                    next_min += timedelta(minutes=1)
                    last = now
                while next_min <= now:
                    local = next_min.astimezone(self.tz)
                    self.wichtel.step(local)
                    if local.minute == 0 and self.sim and not self.live:
                        log.info("%s", self.status_line(local))
                    next_min += timedelta(minutes=1)
                real = time.monotonic()
                self.update(now, (now - last).total_seconds(), real - real_last)
                last, real_last = now, real
                if end is not None and now >= end:
                    log.info("Simulation beendet (%s).", fmt(now))
                    break
                self.stop_event.wait(TICK_SECONDS)
        finally:
            self.shutdown()

    def update(self, now: datetime, dt_sim: float, dt_real: float) -> None:
        cfg, w = self.cfg, self.wichtel
        leds, oven = cfg["leds"], cfg["ofen"]
        dark = self.sun.is_dark(
            now, cfg["dunkel"]["vor_sonnenuntergang_min"], cfg["dunkel"]["nach_sonnenaufgang_min"]
        )

        # Innenlicht: an, wenn dunkel UND wach. Der Raum des Wichtels ist heller.
        room_zone = leds["raeume"].get(w.room)
        targets = dict.fromkeys(self.zones, 0.0)
        if w.awake and dark:
            for zone in targets:
                targets[zone] = float(leds["grundhelligkeit"])
            if room_zone:
                targets[room_zone] = float(leds["raumhelligkeit"])
        elif w.night_up and dark and room_zone:
            targets[room_zone] = float(leds["nachtlicht"])
        inside_on = any(t > 0 for t in targets.values())
        fade = float(leds["fade_sekunden"] if inside_on else leds["einschlaf_fade_sekunden"])
        for zone, target in targets.items():
            self.levels[zone] = approach(self.levels[zone], target, dt_sim / fade)

        # Ofen: brennt, wenn es draußen kalt ist und der Wichtel wach ist; danach Glut.
        temp = self.weather.temperature
        cold = temp is not None and temp < float(oven["temperatur_grenze"])
        oven_target = 0.0
        if self.oven_pixels and cold:
            if w.awake:
                oven_target = 1.0
            elif w.asleep_since is not None:
                minutes = (now - w.asleep_since).total_seconds() / 60
                if minutes < float(oven["glut_minuten"]):
                    oven_target = float(oven["glut_helligkeit"]) * (1 - minutes / float(oven["glut_minuten"]))
        rate = 120.0 if oven_target > self.oven_level else 30.0
        self.oven_level = approach(self.oven_level, oven_target, dt_sim / rate)
        self.fire.update(dt_real)

        # Pixel zusammensetzen
        maxb = float(leds["max_helligkeit"])
        r, g, b = (int(c) for c in leds["farbe"])
        px: list[Color] = [(0, 0, 0)] * self.n
        for zone, (first, last) in self.zones.items():
            level = self.levels[zone] * maxb
            if level > 0:
                px[first : last + 1] = [(int(r * level + 0.5), int(g * level + 0.5), int(b * level + 0.5))] * (
                    last - first + 1
                )
        if self.oven_pixels:
            flames = self.fire.colors(self.oven_level, float(oven["helligkeit"]) * maxb)
            for i, color in zip(self.oven_pixels, flames):
                if self.oven_level > 0.002 or oven["nur_ofen"]:
                    px[i] = color
        self.pixels = px
        self.pixel_out.show(px)

        # Außenlicht
        self.outside_on = bool(cfg["aussenlicht"]["aktiv"]) and self.sun.outside_light_on(now, self.outside_off_at)
        self.relay_out.set(self.outside_on)
        self.lantern_on = bool(cfg["laterne"]["aktiv"]) and self.sun.outside_light_on(now, self.lantern_off_at)
        self.lantern_out.set(self.lantern_on)

        oven_mode = "brennt" if oven_target >= 1 else ("Glut" if oven_target > 0 else "aus")
        modes = (inside_on, self.outside_on, oven_mode, self.lantern_on)
        if modes != self._last_modes:
            old = self._last_modes or (None, None, None, None)
            if inside_on != old[0]:
                self._event(now, "Innenlicht " + ("an" if inside_on else "aus (dimmt langsam ab)"))
            if self.outside_on != old[1]:
                self._event(now, "Außenlicht " + ("AN" if self.outside_on else "aus"))
            if oven_mode != old[2]:
                self._event(now, f"Ofen: {oven_mode} (draußen {self.weather.describe()})")
            if self.lantern_on != old[3]:
                self._event(now, "Laterne " + ("AN" if self.lantern_on else "aus"))
            self._last_modes = modes

        if self.live:
            real = time.monotonic()
            if real - self._last_live >= 0.1:
                self._last_live = real
                sys.stdout.write("\r" + self.status_line(now) + "\x1b[K")
                sys.stdout.flush()

    # -------------------------------------------------------------- Anzeige
    def _block(self, color: Color, label: str) -> str:
        if self.color:
            r, g, b = color
            return f"\x1b[48;2;{r};{g};{b}m  \x1b[0m"
        return label

    def status_line(self, now: datetime) -> str:
        w = self.wichtel
        zones = " ".join(
            self._block(self.pixels[(a + b) // 2], f"{int(self.levels[z] * 100):3d}%") for z, (a, b) in self.zones.items()
        )
        oven = self._block(self.pixels[self.oven_pixels[0]], f"{int(self.oven_level * 100):3d}%") if self.oven_pixels else "-"
        temp = self.weather.temperature
        return (
            f"{fmt(now)}  {w.state:<10} {w.doing:<23} @{ROOM_NAMES.get(w.room, w.room):<13} "
            f"müde {w.tiredness:.2f} | innen {zones} | Ofen {oven} | außen {'AN ' if self.outside_on else 'aus'} | Laterne {'AN ' if self.lantern_on else 'aus'} | "
            + (f"{temp:5.1f} °C" if temp is not None else "  ? °C")
        )

    def _event(self, now: datetime, message: str) -> None:
        log.info("%s  %s", fmt(now), message)

    def _log_intro(self, now: datetime) -> None:
        st = self.cfg["standort"]
        sunrise, sunset = self.sun.get(now.date())
        mode = "SIMULATION" if self.sim else "Hardware"
        if self.clock.simulated:
            mode += f", Zeitraffer x{self.clock.speed:g}"
        log.info("Wichtelhaus %s (%s)", __version__, mode)
        log.info(
            "Standort %s (%.3f, %.3f): Sonnenaufgang %s, Sonnenuntergang %s",
            st["name"], float(st["breite"]), float(st["laenge"]), f"{sunrise:%H:%M}", f"{sunset:%H:%M}",
        )
        log.info("Außentemperatur: %s, Ofen ab unter %.1f °C", self.weather.describe(), float(self.cfg["ofen"]["temperatur_grenze"]))
        if now.year < 2024:
            log.warning("Die Systemuhr scheint falsch zu gehen (%s). Läuft NTP?", now)

    # --------------------------------------------------------- Hardware-Test
    def hardware_test(self) -> None:
        """Verkabelung prüfen: jede Zone einzeln, dann Ofen, dann Relais."""
        self._install_signals()
        leds = self.cfg["leds"]
        maxb = float(leds["max_helligkeit"])
        r, g, b = (int(c) for c in leds["farbe"])
        color = (int(r * maxb), int(g * maxb), int(b * maxb))
        try:
            for zone, (first, last) in self.zones.items():
                if self.stop_event.is_set():
                    return
                log.info("Test: Zone %s (LED %d–%d) leuchtet", zone, first, last)
                px = [(0, 0, 0)] * self.n
                px[first : last + 1] = [color] * (last - first + 1)
                self.pixel_out.show(px)
                self.stop_event.wait(3)
            if self.oven_pixels:
                log.info("Test: Ofen flackert (LED %s)", ", ".join(map(str, self.oven_pixels)))
                end = time.monotonic() + 6
                while time.monotonic() < end and not self.stop_event.is_set():
                    self.fire.update(TICK_SECONDS)
                    px = [(0, 0, 0)] * self.n
                    for i, c in zip(self.oven_pixels, self.fire.colors(1.0, float(self.cfg["ofen"]["helligkeit"]) * maxb)):
                        px[i] = c
                    self.pixel_out.show(px)
                    time.sleep(TICK_SECONDS)
            self.pixel_out.off()
            log.info("Test: Außenlicht-Relais 3 Sekunden AN")
            self.relay_out.set(True)
            self.stop_event.wait(3)
            self.relay_out.set(False)
            log.info("Test: Laternen-Relais 3 Sekunden AN")
            self.lantern_out.set(True)
            self.stop_event.wait(3)
            self.lantern_out.set(False)
            log.info("Test fertig.")
        finally:
            self.shutdown()

    # ------------------------------------------------------------- Beenden
    def _install_signals(self) -> None:
        def handler(signum, _frame):
            if self.live:
                sys.stdout.write("\n")
            log.info("Signal %s empfangen, beende …", signal.Signals(signum).name)
            self.stop_event.set()

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def shutdown(self) -> None:
        self.weather.stop()
        try:
            self.pixel_out.off()
        except Exception:
            log.exception("LEDs konnten nicht ausgeschaltet werden")
        for name, relay in (("Außenlicht", self.relay_out), ("Laterne", self.lantern_out)):
            try:
                relay.close()
            except Exception:
                log.exception("Relais %s konnte nicht ausgeschaltet werden", name)
        if self.live:
            sys.stdout.write("\n")
        log.info("LEDs, Außenlicht und Laterne sind aus. Gute Nacht!")


# ----------------------------------------------------------------- Kommandozeile
def parse_start(text: str, tz) -> datetime:
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=tz)
        except ValueError:
            continue
    raise SystemExit(f"--start: '{text}' bitte als 'JJJJ-MM-TT HH:MM' angeben")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="wichtelhaus", description="Ein unsichtbarer Wichtel steuert das Wichtelhaus.")
    p.add_argument("--config", default=str(DEFAULT_CONFIG), help="Pfad zur config.yaml")
    p.add_argument("--sim", action="store_true", help="ohne Hardware, Ausgabe in der Konsole")
    p.add_argument("--speed", type=float, default=1.0, help="Zeitraffer-Faktor (nur mit --sim), z. B. 720 = 1 Tag in 2 Minuten")
    p.add_argument("--start", help="simulierte Startzeit 'JJJJ-MM-TT HH:MM' (nur mit --sim)")
    p.add_argument("--days", type=float, help="nach so vielen (simulierten) Tagen beenden")
    p.add_argument("--temp", type=float, help="Außentemperatur fest vorgeben statt aus dem Internet")
    p.add_argument("--seed", type=int, help="Zufalls-Startwert, damit ein Lauf wiederholbar ist")
    p.add_argument("--live", action="store_true", help="eine laufend aktualisierte Statuszeile (mit Farbe)")
    p.add_argument("--no-color", action="store_true", help="keine ANSI-Farben in der Konsole")
    p.add_argument("--test-hardware", action="store_true", help="Zonen, Ofen und Relais nacheinander testen")
    p.add_argument("-v", "--verbose", action="store_true", help="mehr Details im Log")
    args = p.parse_args(argv)
    if not args.sim and (args.speed != 1.0 or args.start):
        p.error("--speed und --start gehen nur zusammen mit --sim")
    if args.speed <= 0:
        p.error("--speed muss größer als 0 sein")
    return args


def setup_logging(args: argparse.Namespace) -> None:
    # Unter systemd setzt journald selbst die Uhrzeit dazu.
    fmt_ = "%(message)s" if args.sim else "%(levelname)s %(message)s"
    handler = logging.StreamHandler(sys.stdout)
    if args.live:
        class LiveFormatter(logging.Formatter):
            def format(self, record):
                return "\r\x1b[K" + super().format(record)

        handler.setFormatter(LiveFormatter(fmt_))
    else:
        handler.setFormatter(logging.Formatter(fmt_))
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, handlers=[handler])
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if os.name == "nt":
        os.system("")  # ANSI-Farben im Windows-Terminal einschalten
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    setup_logging(args)
    try:
        cfg = load_config(args.config)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        log.error("Konfiguration %s fehlerhaft: %s", args.config, exc)
        return 2
    try:
        house = WichtelHaus(cfg, args)
    except Exception:
        log.exception("Start fehlgeschlagen (Hardware? Läuft das Programm als root?)")
        return 1
    if args.test_hardware:
        house.hardware_test()
    else:
        house.run(days=args.days)
    return 0
