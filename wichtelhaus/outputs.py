"""Ausgänge: echte Hardware (NeoPixel, Relais) oder Simulation ohne Hardware."""
from __future__ import annotations

import logging
from typing import Sequence

log = logging.getLogger(__name__)

Color = tuple[int, int, int]


class SimPixels:
    def __init__(self, count: int):
        self.pixels: list[Color] = [(0, 0, 0)] * count

    def show(self, pixels: Sequence[Color]) -> None:
        self.pixels = list(pixels)

    def off(self) -> None:
        self.pixels = [(0, 0, 0)] * len(self.pixels)


class SimRelay:
    def __init__(self):
        self.on = False

    def set(self, on: bool) -> None:
        self.on = on

    def close(self) -> None:
        self.on = False


class NeoPixelOutput:
    """WS2812-Band an einem GPIO (braucht root)."""

    def __init__(self, pin: int, count: int, pixel_order: str = "GRB"):
        import board  # adafruit-blinka
        import neopixel

        self.count = count
        self.strip = neopixel.NeoPixel(
            getattr(board, f"D{pin}"), count, brightness=1.0, auto_write=False, pixel_order=pixel_order
        )
        self._last: list[Color] = []
        self.off()

    def show(self, pixels: Sequence[Color]) -> None:
        pixels = list(pixels)
        if pixels == self._last:
            return  # spart CPU, wenn sich nichts ändert
        self.strip[0 : self.count] = pixels
        self.strip.show()
        self._last = pixels

    def off(self) -> None:
        self.strip.fill((0, 0, 0))
        self.strip.show()
        self._last = [(0, 0, 0)] * self.count


class RelayOutput:
    """Relais für das Außenlicht. Viele Relais-Module schalten bei LOW (active_low)."""

    def __init__(self, pin: int, active_low: bool = True):
        import board
        import digitalio

        self.active_low = active_low
        self.on = False
        self.io = digitalio.DigitalInOut(getattr(board, f"D{pin}"))
        self.io.switch_to_output(value=self._level(False))

    def _level(self, on: bool) -> bool:
        return (not on) if self.active_low else on

    def set(self, on: bool) -> None:
        if on != self.on:
            self.io.value = self._level(on)
            self.on = on

    def close(self) -> None:
        self.set(False)
        self.io.deinit()


def make_outputs(cfg: dict, sim: bool):
    leds = cfg["leds"]
    outside = cfg["aussenlicht"]
    if sim:
        return SimPixels(leds["anzahl"]), SimRelay()
    pixels = NeoPixelOutput(leds["pin"], leds["anzahl"], leds["pixel_order"])
    relay = RelayOutput(outside["pin"], outside["active_low"]) if outside["aktiv"] else SimRelay()
    return pixels, relay
