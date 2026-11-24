"""Flackerndes Feuer für den virtuellen Ofen. Läuft in Echtzeit, auch im Zeitraffer."""
from __future__ import annotations

import random
from typing import Optional

Color = tuple[int, int, int]


class Fire:
    def __init__(self, count: int, rng: Optional[random.Random] = None):
        self.rng = rng or random.Random()
        self.heat = [0.6] * count
        self.target = [0.6] * count
        self.glow = 0.8
        self.glow_target = 0.8

    def update(self, dt: float) -> None:
        """Flammen um ``dt`` Sekunden (Echtzeit) weiterbewegen."""
        dt = max(0.0, min(dt, 0.2))
        r = self.rng
        # Die ganze Flamme "atmet" langsam …
        if r.random() < dt * 2:
            self.glow_target = r.uniform(0.6, 1.0)
        self.glow += (self.glow_target - self.glow) * min(1.0, dt * 3)
        # … und jede LED zuckt für sich.
        for i in range(len(self.heat)):
            if r.random() < dt * 12:
                self.target[i] = r.uniform(0.15, 1.0)
            self.heat[i] += (self.target[i] - self.heat[i]) * min(1.0, dt * 15)

    def colors(self, intensity: float, scale: float) -> list[Color]:
        """Farben der Ofen-LEDs.

        intensity: 0..1, 1 = Feuer brennt, kleine Werte = Glut (tiefrot, ruhiger)
        scale: Helligkeitsfaktor (Ofen-Helligkeit x maximale Helligkeit)
        """
        out: list[Color] = []
        for h in self.heat:
            flicker = 0.45 + 0.55 * h if intensity > 0.5 else 0.8 + 0.2 * h
            v = max(0.0, min(1.0, intensity * scale * self.glow * flicker))
            green = 20 + 105 * h * min(1.0, intensity)  # heiß = orange, kühl = rot
            out.append((int(255 * v + 0.5), int(green * v + 0.5), int(4 * v + 0.5)))
        return out
