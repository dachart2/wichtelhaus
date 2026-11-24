"""Der unsichtbare Wichtel: Tagesrhythmus, Müdigkeit, Aktivitäten und Räume.

Der Wichtel lebt minutenweise. Jeden Tag würfelt er neu aus, wann er aufwacht
und wann er schlafen geht. Tagsüber wechselt er zwischen Aktivitäten in
verschiedenen Räumen, wird dabei müde und macht ab und zu kurze Ausflüge in
andere Räume. Manche Nächte steht er kurz auf.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Callable, Optional, Union

SCHLAEFT = "schläft"
WACH = "wach"
NACHTS_AUF = "nachts auf"

ROOMS = ("kueche", "wohnbereich", "arbeitsecke", "fenster", "schlafbereich")
ROOM_NAMES = {
    "kueche": "Küche",
    "wohnbereich": "Wohnbereich",
    "arbeitsecke": "Arbeitsecke",
    "fenster": "Fenster",
    "schlafbereich": "Schlafbereich",
}
EXCURSION_REASONS = {
    "kueche": "holt sich einen Keks",
    "wohnbereich": "sucht etwas",
    "arbeitsecke": "holt Werkzeug",
    "fenster": "schaut kurz hinaus",
    "schlafbereich": "holt seine Mütze",
}

BASE_TIREDNESS = 0.001  # pro wacher Minute, etwa 0.9 nach 15 Stunden


@dataclass(frozen=True)
class Activity:
    name: str
    room: str
    min_minutes: int
    max_minutes: int
    tiredness: float  # Faktor für die Müdigkeit pro Minute (negativ = erholt sich)
    meal: bool = False


ACTIVITIES = {
    a.name: a
    for a in (
        Activity("Frühstück", "kueche", 20, 40, 0.5, meal=True),
        Activity("Mittagessen", "kueche", 25, 45, 0.5, meal=True),
        Activity("Abendessen", "kueche", 30, 50, 0.5, meal=True),
        Activity("Aufräumen", "wohnbereich", 20, 60, 1.3),
        Activity("Basteln", "arbeitsecke", 30, 120, 1.0),
        Activity("Spielen", "wohnbereich", 20, 75, 1.5),
        Activity("Aus dem Fenster schauen", "fenster", 5, 25, 0.7),
        Activity("Ausruhen", "schlafbereich", 15, 45, -2.0),
    )
}
MEALS = (
    ("Mittagessen", time(12, 0), time(13, 30)),
    ("Abendessen", time(17, 30), time(19, 0)),
)


def parse_hhmm(value: Union[str, int]) -> time:
    """'HH:MM' -> time. YAML macht aus unquotiertem 23:30 die Zahl 1410 (Minuten)."""
    if isinstance(value, int):
        hours, minutes = divmod(value, 60)
    else:
        hours, minutes = (int(x) for x in str(value).strip().split(":"))
    return time(hours, minutes)


def random_time_between(start: time, end: time, rng: random.Random) -> time:
    """Zufällige Uhrzeit (minutengenau) zwischen start und end am selben Tag."""
    s = start.hour * 60 + start.minute
    e = end.hour * 60 + end.minute
    if s >= e:
        raise ValueError(f"Die Startzeit {start:%H:%M} muss vor der Endzeit {end:%H:%M} liegen.")
    m = rng.randint(s, e)
    return time(m // 60, m % 60)


@dataclass
class DayPlan:
    day: date
    wake: datetime
    sleep: datetime
    night_up_start: Optional[datetime] = None
    night_up_end: Optional[datetime] = None

    def is_night_up(self, now: datetime) -> bool:
        return self.night_up_start is not None and self.night_up_start <= now < self.night_up_end


EventCallback = Callable[[datetime, str], None]


class Wichtel:
    def __init__(
        self,
        cfg: dict,
        tz: tzinfo,
        rng: Optional[random.Random] = None,
        on_event: Optional[EventCallback] = None,
        plan_seed: object = 0,
    ):
        self.tz = tz
        self.plan_seed = plan_seed
        self.rng = rng or random.Random()
        self.on_event: EventCallback = on_event or (lambda now, msg: None)
        self.wake_window = tuple(parse_hhmm(x) for x in cfg["aufwachen"])
        self.sleep_window = tuple(parse_hhmm(x) for x in cfg["schlafen"])
        self.night_up_chance = float(cfg["nachts_aufstehen"])
        self.excursion_chance = float(cfg["ausflug_chance"])
        self._plans: dict[date, DayPlan] = {}
        self.state: Optional[str] = None
        self.activity: Optional[Activity] = None
        self.activity_end: Optional[datetime] = None
        self.home_room = "schlafbereich"
        self.excursion_room: Optional[str] = None
        self.excursion_end: Optional[datetime] = None
        self.tiredness = 0.0
        self.asleep_since: Optional[datetime] = None
        self.meals_done: set[str] = set()

    # ------------------------------------------------------------------ Status
    @property
    def awake(self) -> bool:
        return self.state == WACH

    @property
    def night_up(self) -> bool:
        return self.state == NACHTS_AUF

    @property
    def room(self) -> str:
        return self.excursion_room or self.home_room

    @property
    def doing(self) -> str:
        if self.state == WACH and self.activity:
            return self.activity.name
        if self.state == NACHTS_AUF:
            return "trinkt ein Glas Wasser"
        return "schläft"

    # ------------------------------------------------------------------- Pläne
    def plan_for(self, day: date) -> DayPlan:
        plan = self._plans.get(day)
        if plan is None:
            # Fester Zufall pro Datum: der Tagesplan bleibt bei einem Neustart gleich.
            rng = random.Random(f"wichtel-{self.plan_seed}-{day.isoformat()}")
            wake = datetime.combine(day, random_time_between(*self.wake_window, rng), tzinfo=self.tz)
            sleep = datetime.combine(day, random_time_between(*self.sleep_window, rng), tzinfo=self.tz)
            plan = DayPlan(day, wake, sleep)
            if rng.random() < self.night_up_chance:
                start = sleep + timedelta(minutes=rng.randint(60, 300))
                end = start + timedelta(minutes=rng.randint(3, 10))
                latest = datetime.combine(day + timedelta(days=1), self.wake_window[0], tzinfo=self.tz)
                if end < latest - timedelta(minutes=30):
                    plan.night_up_start, plan.night_up_end = start, end
            self._plans[day] = plan
            for old in [d for d in self._plans if d < day - timedelta(days=3)]:
                del self._plans[old]
        return plan

    # ------------------------------------------------------------------ Ablauf
    def resync(self, now: datetime) -> None:
        """Nach einem Zeitsprung (z. B. NTP nach dem Booten) neu einstellen."""
        self.state = None
        self._end_excursion()
        self.step(now)

    def step(self, now: datetime) -> None:
        """Eine Minute Wichtel-Leben."""
        today = self.plan_for(now.date())
        yesterday = self.plan_for(now.date() - timedelta(days=1))
        should_be_awake = today.wake <= now < today.sleep

        if self.state is None:
            self._init_state(now, today, yesterday, should_be_awake)
            return

        if should_be_awake:
            if self.state != WACH:
                self._wake_up(now, today)
            else:
                self._live_minute(now, today)
            return

        if self.state == WACH:
            self._go_to_bed(now)
        up = today.is_night_up(now) or yesterday.is_night_up(now)
        if up and self.state == SCHLAEFT:
            self.state = NACHTS_AUF
            self.home_room = "kueche"
            self.on_event(now, "Der Wichtel steht nachts auf und trinkt ein Glas Wasser (Küche)")
        elif not up and self.state == NACHTS_AUF:
            self.state = SCHLAEFT
            self.home_room = "schlafbereich"
            self.on_event(now, "… und schlüpft wieder unter die Decke")

    def _init_state(self, now: datetime, today: DayPlan, yesterday: DayPlan, awake: bool) -> None:
        if awake:
            self.state = WACH
            minutes = (now - today.wake).total_seconds() / 60
            self.tiredness = min(0.95, minutes * BASE_TIREDNESS)
            self.meals_done = {"Frühstück"} | {name for name, _, end in MEALS if now.time() >= end}
            self._start_activity(now, self._choose_activity(now))
            self.on_event(
                now,
                f"Start: Der Wichtel ist wach ({self.doing}, {ROOM_NAMES[self.room]}), "
                f"geht heute um {today.sleep:%H:%M} schlafen",
            )
        else:
            self.state = SCHLAEFT
            self.home_room = "schlafbereich"
            self.asleep_since = today.sleep if now >= today.sleep else yesterday.sleep
            next_wake = today.wake if now < today.wake else self.plan_for(now.date() + timedelta(days=1)).wake
            self.on_event(now, f"Start: Der Wichtel schläft, wacht um {next_wake:%H:%M} auf")

    def _wake_up(self, now: datetime, plan: DayPlan) -> None:
        self.state = WACH
        self.asleep_since = None
        self.tiredness = self.rng.uniform(0.0, 0.08)
        self.meals_done = set()
        self._start_activity(now, ACTIVITIES["Frühstück"])
        self.on_event(
            now, f"Der Wichtel wacht auf und macht Frühstück (geht heute um {plan.sleep:%H:%M} schlafen)"
        )

    def _go_to_bed(self, now: datetime, early: bool = False) -> None:
        self.state = SCHLAEFT
        self.activity = None
        self._end_excursion()
        self.home_room = "schlafbereich"
        self.asleep_since = now
        next_wake = self.plan_for(now.date() + timedelta(days=1)).wake
        note = ", früher als geplant" if early else ""
        self.on_event(
            now, f"Der Wichtel geht schlafen (Müdigkeit {self.tiredness:.2f}{note}), wacht um {next_wake:%H:%M} auf"
        )

    def _live_minute(self, now: datetime, plan: DayPlan) -> None:
        act = self.activity
        assert act is not None
        self.tiredness = max(0.0, min(1.2, self.tiredness + BASE_TIREDNESS * act.tiredness))

        # Sehr müde am Abend: früher ins Bett
        if self.tiredness >= 1.0 and now.time() >= self.sleep_window[0]:
            plan.sleep = now
            self._go_to_bed(now, early=True)
            return

        if self.excursion_room and now >= self.excursion_end:
            self._end_excursion()

        if now >= self.activity_end:
            nxt = self._choose_activity(now)
            self._start_activity(now, nxt)
            self.on_event(now, f"{nxt.name} ({ROOM_NAMES[nxt.room]}), Müdigkeit {self.tiredness:.2f}")
            return

        if not self.excursion_room and not act.meal and self.rng.random() < self.excursion_chance:
            room = self.rng.choice([r for r in ROOMS if r != self.home_room])
            self.excursion_room = room
            self.excursion_end = now + timedelta(minutes=self.rng.randint(1, 4))
            self.on_event(now, f"kurzer Ausflug: {EXCURSION_REASONS[room]} ({ROOM_NAMES[room]})")

    def _choose_activity(self, now: datetime) -> Activity:
        t = now.time()
        for name, start, end in MEALS:
            if name not in self.meals_done and start <= t < end:
                return ACTIVITIES[name]
        weights = {
            "Aufräumen": 2.0,
            "Basteln": 3.0,
            "Spielen": 2.5 * max(0.1, 1.1 - self.tiredness),
            "Aus dem Fenster schauen": 1.5,
            "Ausruhen": 0.3 + 3.0 * self.tiredness,
        }
        if self.activity and self.activity.name in weights:
            weights[self.activity.name] *= 0.3  # nicht ständig dasselbe
        names = list(weights)
        return ACTIVITIES[self.rng.choices(names, weights=[weights[n] for n in names])[0]]

    def _start_activity(self, now: datetime, act: Activity) -> None:
        self.activity = act
        self.activity_end = now + timedelta(minutes=self.rng.randint(act.min_minutes, act.max_minutes))
        self.home_room = act.room
        self._end_excursion()
        if act.meal:
            self.meals_done.add(act.name)

    def _end_excursion(self) -> None:
        self.excursion_room = None
        self.excursion_end = None
