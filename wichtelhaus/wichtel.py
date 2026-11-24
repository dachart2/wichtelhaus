"""Der unsichtbare Wichtel – mit freiem Willen.

Der Wichtel hat einen Terminplan (wann er aufstehen und schlafen gehen
*möchte*), aber er entscheidet selbst:

- Morgens dreht er sich bei schlechter Laune oder Kälte noch einmal um.
- Abends bleibt er länger auf, wenn er gerade gut gelaunt bastelt oder spielt,
  und geht früher ins Bett, wenn er sehr müde ist.
- Er isst, wenn er Hunger hat, nicht nach der Uhr, und holt sich zwischendurch
  einen Keks.
- Was er tut, hängt von Laune, Müdigkeit und Wetter ab (bei Schnee schaut er
  gern aus dem Fenster, bei Kälte kuschelt er sich lieber ein).
- Manche Nächte kann er nicht schlafen und steht kurz auf.

Alle Entscheidungen bleiben innerhalb fester Grenzen, damit das Haus nachts
nicht taghell ist.
"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
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
HUNGER_PER_MIN = 1 / 280  # nach gut 4 Stunden richtig hungrig
PLAN_AHEAD_DAYS = 7  # so viele Tage im Voraus steht der Terminplan fest
LATEST_SLEEP = time(23, 55)  # Schlafengehen muss am selben Tag bleiben

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Activity:
    name: str
    room: str
    min_minutes: int
    max_minutes: int
    tiredness: float  # Faktor für die Müdigkeit pro Minute (negativ = erholt sich)
    meal: bool = False
    fills: float = 0.0  # so viel Hunger bleibt nach dem Essen übrig


ACTIVITIES = {
    a.name: a
    for a in (
        Activity("Frühstück", "kueche", 20, 40, 0.5, meal=True, fills=0.05),
        Activity("Mittagessen", "kueche", 25, 45, 0.5, meal=True, fills=0.05),
        Activity("Abendessen", "kueche", 30, 50, 0.5, meal=True, fills=0.05),
        Activity("Jause", "kueche", 10, 20, 0.5, meal=True, fills=0.3),
        Activity("Aufräumen", "wohnbereich", 20, 60, 1.3),
        Activity("Basteln", "arbeitsecke", 30, 120, 1.0),
        Activity("Spielen", "wohnbereich", 20, 75, 1.5),
        Activity("Aus dem Fenster schauen", "fenster", 5, 25, 0.7),
        Activity("Ausruhen", "schlafbereich", 15, 45, -1.5),
    )
}
FUN = {"Basteln", "Spielen"}


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


def _shift(t: time, minutes: int) -> time:
    m = max(0, min(23 * 60 + 59, t.hour * 60 + t.minute + minutes))
    return time(m // 60, m % 60)


@dataclass
class DayPlan:
    day: date
    wake: datetime
    sleep: datetime
    night_up_start: Optional[datetime] = None
    night_up_end: Optional[datetime] = None
    decided: set = field(default_factory=set)  # schon getroffene Entscheidungen (nicht gespeichert)

    def is_night_up(self, now: datetime) -> bool:
        return self.night_up_start is not None and self.night_up_start <= now < self.night_up_end


@dataclass
class Environment:
    """Was der Wichtel von draußen mitbekommt."""

    temperature: Optional[float] = None
    snowing: bool = False
    raining: bool = False
    dark: bool = False

    @property
    def cold(self) -> bool:
        return self.temperature is not None and self.temperature < 0


EventCallback = Callable[[datetime, str], None]


class Wichtel:
    def __init__(
        self,
        cfg: dict,
        tz: tzinfo,
        rng: Optional[random.Random] = None,
        on_event: Optional[EventCallback] = None,
        plan_file: Optional[Path] = None,
    ):
        self.tz = tz
        self.plan_file = Path(plan_file) if plan_file else None
        self._planned_for: Optional[date] = None
        self.rng = rng or random.Random()
        self.on_event: EventCallback = on_event or (lambda now, msg: None)
        self.wake_window = tuple(parse_hhmm(x) for x in cfg["aufwachen"])
        self.sleep_window = tuple(parse_hhmm(x) for x in cfg["schlafen"])
        self.night_up_chance = float(cfg["nachts_aufstehen"])
        self.excursion_chance = float(cfg["ausflug_chance"])
        # Grenzen für den freien Willen
        self.latest_wake = _shift(self.wake_window[1], 60)
        self.earliest_sleep = _shift(self.sleep_window[0], -30)
        self.latest_sleep = min(_shift(self.sleep_window[1], 60), LATEST_SLEEP)

        self._plans: dict[date, DayPlan] = {}
        self.env = Environment()
        self.state: Optional[str] = None
        self.activity: Optional[Activity] = None
        self.activity_end: Optional[datetime] = None
        self.home_room = "schlafbereich"
        self.excursion_room: Optional[str] = None
        self.excursion_end: Optional[datetime] = None
        self.tiredness = 0.0
        self.hunger = 0.3
        self.mood = 0.6  # Laune 0 (grantig) .. 1 (bestens)
        self.asleep_since: Optional[datetime] = None
        self.meals_done: set[str] = set()
        self._load_plans()

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

    @property
    def mood_text(self) -> str:
        if self.mood >= 0.75:
            return "bestens gelaunt"
        if self.mood >= 0.45:
            return "zufrieden"
        return "ein bisschen grantig"

    # ------------------------------------------------------------------- Pläne
    def plan_for(self, day: date) -> DayPlan:
        plan = self._plans.get(day)
        if plan is None:
            plan = self._new_plan(day)
            self._plans[day] = plan
        return plan

    def _new_plan(self, day: date) -> DayPlan:
        """Echt zufälliger Vorsatz: Aufstehen, Schlafengehen, nächtliches Aufstehen."""
        rng = self.rng
        wake = datetime.combine(day, random_time_between(*self.wake_window, rng), tzinfo=self.tz)
        sleep = datetime.combine(day, random_time_between(*self.sleep_window, rng), tzinfo=self.tz)
        plan = DayPlan(day, wake, sleep)
        if rng.random() < self.night_up_chance:
            start = sleep + timedelta(minutes=rng.randint(60, 300))
            end = start + timedelta(minutes=rng.randint(3, 10))
            if end < self._at(day + timedelta(days=1), self.wake_window[0]) - timedelta(minutes=30):
                plan.night_up_start, plan.night_up_end = start, end
        return plan

    def plan_ahead(self, today: date) -> None:
        """Terminplan von gestern bis PLAN_AHEAD_DAYS Tage voraus festlegen und speichern."""
        for offset in range(-1, PLAN_AHEAD_DAYS + 1):
            self.plan_for(today + timedelta(days=offset))
        for old in [d for d in self._plans if d < today - timedelta(days=2)]:
            del self._plans[old]
        self._planned_for = today
        self.save_plans()

    def upcoming(self, today: date, days: int = PLAN_AHEAD_DAYS) -> list[DayPlan]:
        return [self.plan_for(today + timedelta(days=i)) for i in range(days)]

    def _at(self, day: date, t: time) -> datetime:
        return datetime.combine(day, t, tzinfo=self.tz)

    # ------------------------------------------------------------------ Ablauf
    def resync(self, now: datetime) -> None:
        """Nach einem Zeitsprung (z. B. NTP nach dem Booten) neu einstellen."""
        self.state = None
        self._end_excursion()
        self.step(now)

    def step(self, now: datetime, env: Optional[Environment] = None) -> None:
        """Eine Minute Wichtel-Leben."""
        if env is not None:
            self.env = env
        if self._planned_for != now.date():
            self.plan_ahead(now.date())
        today = self.plan_for(now.date())
        yesterday = self.plan_for(now.date() - timedelta(days=1))

        if self.state is None:
            self._init_state(now, today, yesterday)
            return

        should_be_awake = today.wake <= now < today.sleep

        # Freier Wille an den Übergängen
        if should_be_awake and self.state != WACH and "wake" not in today.decided:
            today.decided.add("wake")
            if self._decide_snooze(now, today):
                return
        if not should_be_awake and self.state == WACH and "sleep" not in today.decided and now.date() == today.day:
            today.decided.add("sleep")
            if self._decide_stay_up(now, today):
                self._live_minute(now, today)
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
            why = "kann nicht schlafen" if self.tiredness < 0.6 else "hat Durst"
            self.on_event(now, f"Der Wichtel {why}, steht auf und trinkt ein Glas Wasser (Küche)")
        elif not up and self.state == NACHTS_AUF:
            self.state = SCHLAEFT
            self.home_room = "schlafbereich"
            self.on_event(now, "… und schlüpft wieder unter die Decke")

    # ------------------------------------------------------- Entscheidungen
    def _decide_snooze(self, now: datetime, plan: DayPlan) -> bool:
        """Beim Wecken: noch liegen bleiben?"""
        chance = 0.2 + 0.3 * (1 - self.mood)
        reasons = []
        if self.env.cold:
            chance += 0.15
            reasons.append("draußen ist es eisig")
        if self.env.raining:
            chance += 0.1
            reasons.append("es regnet")
        if self.env.snowing:
            chance -= 0.15  # Schnee! Schnell ans Fenster
        latest = self._at(plan.day, self.latest_wake)
        if self.rng.random() >= chance or now >= latest:
            return False
        minutes = self.rng.randint(10, 45)
        plan.wake = min(now + timedelta(minutes=minutes), latest)
        self.save_plans()
        why = f" ({', '.join(reasons)})" if reasons else ""
        self.on_event(now, f"Der Wichtel dreht sich noch einmal um{why} und schläft bis {plan.wake:%H:%M}")
        return True

    def _decide_stay_up(self, now: datetime, plan: DayPlan) -> bool:
        """Zur geplanten Schlafenszeit: noch ein bisschen aufbleiben?"""
        act = self.activity
        if act is None or act.name not in FUN or self.tiredness >= 0.9:
            return False
        if self.rng.random() >= 0.25 + 0.35 * self.mood:
            return False
        latest = self._at(plan.day, self.latest_sleep)
        if now >= latest:
            return False
        plan.sleep = min(now + timedelta(minutes=self.rng.randint(10, 45)), latest)
        self.activity_end = max(self.activity_end or now, plan.sleep)
        self.save_plans()
        what = "will sein Bastelprojekt noch fertig machen" if act.name == "Basteln" else "will unbedingt noch weiterspielen"
        self.on_event(now, f"Der Wichtel {what} und bleibt bis {plan.sleep:%H:%M} auf")
        return True

    # ----------------------------------------------------------------- Phasen
    def _init_state(self, now: datetime, today: DayPlan, yesterday: DayPlan) -> None:
        self.mood = self.rng.uniform(0.3, 1.0)
        if today.wake <= now < today.sleep:
            today.decided.add("wake")
            self.state = WACH
            minutes = (now - today.wake).total_seconds() / 60
            self.tiredness = min(0.95, minutes * BASE_TIREDNESS)
            self.hunger = self.rng.uniform(0.1, 0.6)
            self.meals_done = {"Frühstück"}
            self._start_activity(now, self._choose_activity(now))
            self.on_event(
                now,
                f"Start: Der Wichtel ist wach ({self.doing}, {ROOM_NAMES[self.room]}, {self.mood_text}), "
                f"möchte heute um {today.sleep:%H:%M} schlafen gehen",
            )
        else:
            self.state = SCHLAEFT
            self.home_room = "schlafbereich"
            self.asleep_since = today.sleep if now >= today.sleep else yesterday.sleep
            if now >= today.sleep:
                today.decided.update({"wake", "sleep"})
            next_wake = today.wake if now < today.wake else self.plan_for(now.date() + timedelta(days=1)).wake
            self.on_event(now, f"Start: Der Wichtel schläft, möchte um {next_wake:%H:%M} aufstehen")

    def _wake_up(self, now: datetime, plan: DayPlan) -> None:
        self.state = WACH
        self.asleep_since = None
        self.tiredness = self.rng.uniform(0.0, 0.08)
        self.hunger = 0.7
        self.meals_done = set()
        self.mood = self.rng.uniform(0.3, 1.0)
        if self.env.snowing:
            self.mood = min(1.0, self.mood + 0.2)
        elif self.env.raining:
            self.mood = max(0.0, self.mood - 0.1)
        self._start_activity(now, ACTIVITIES["Frühstück"])
        self.on_event(
            now,
            f"Der Wichtel wacht auf, ist {self.mood_text} und macht Frühstück "
            f"(möchte heute um {plan.sleep:%H:%M} schlafen gehen)",
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
            now, f"Der Wichtel geht schlafen (Müdigkeit {self.tiredness:.2f}{note}), möchte um {next_wake:%H:%M} aufstehen"
        )

    def _live_minute(self, now: datetime, plan: DayPlan) -> None:
        act = self.activity
        assert act is not None
        self.tiredness = max(0.0, min(1.2, self.tiredness + BASE_TIREDNESS * act.tiredness))
        if not act.meal:
            self.hunger = min(1.2, self.hunger + HUNGER_PER_MIN)

        # Sehr müde am Abend: früher ins Bett
        if self.tiredness >= 1.0 and now.time() >= self.earliest_sleep and "sleep" not in plan.decided:
            plan.decided.add("sleep")
            plan.sleep = now
            self.save_plans()
            self._go_to_bed(now, early=True)
            return

        if self.excursion_room and now >= self.excursion_end:
            self._end_excursion()

        # Großer Hunger unterbricht fast alles (außer Essen)
        if not act.meal and self.hunger >= 1.0:
            self.activity_end = now

        if now >= self.activity_end:
            nxt = self._choose_activity(now)
            self._start_activity(now, nxt)
            extra = " – es schneit!" if nxt.room == "fenster" and self.env.snowing else ""
            self.on_event(
                now,
                f"{nxt.name} ({ROOM_NAMES[nxt.room]}){extra}, müde {self.tiredness:.2f}, hungrig {self.hunger:.2f}",
            )
            return

        if not self.excursion_room and not act.meal:
            hungry = self.hunger >= 0.6
            if self.rng.random() < self.excursion_chance * (1.5 if hungry else 1.0):
                if hungry and self.home_room != "kueche" and self.rng.random() < 0.5:
                    room = "kueche"
                    self.hunger = max(0.0, self.hunger - 0.05)  # ein Keks macht nicht satt
                else:
                    room = self.rng.choice([r for r in ROOMS if r != self.home_room])
                self.excursion_room = room
                self.excursion_end = now + timedelta(minutes=self.rng.randint(1, 4))
                self.on_event(now, f"kurzer Ausflug: {EXCURSION_REASONS[room]} ({ROOM_NAMES[room]})")

    def _meal_for(self, now: datetime) -> Activity:
        h = now.hour + now.minute / 60
        if "Frühstück" not in self.meals_done and h < 10.5:
            return ACTIVITIES["Frühstück"]
        if "Mittagessen" not in self.meals_done and 11 <= h < 14.5:
            return ACTIVITIES["Mittagessen"]
        if "Abendessen" not in self.meals_done and 17 <= h < 20.5:
            return ACTIVITIES["Abendessen"]
        return ACTIVITIES["Jause"]

    def _choose_activity(self, now: datetime) -> Activity:
        meal = self._meal_for(now)
        if self.hunger >= 0.75 or (meal.name != "Jause" and self.hunger >= 0.45):
            return meal  # bei großem Hunger, oder zur Essenszeit schon bei mittlerem
        t, m, env = self.tiredness, self.mood, self.env
        weights = {
            "Aufräumen": 2.0 * (1.3 - m),
            "Basteln": 3.0 * (0.8 + 0.4 * m),
            "Spielen": 2.5 * max(0.1, 1.1 - t) * (0.6 + m),
            "Aus dem Fenster schauen": 1.5 * (2.0 if env.snowing else 1.0) * (1.3 if env.dark else 1.0),
            "Ausruhen": 0.3 + 3.0 * t + (0.4 if env.cold else 0.0),
        }
        if self.activity and self.activity.name in weights:
            weights[self.activity.name] *= 0.3  # nicht ständig dasselbe
        names = list(weights)
        return ACTIVITIES[self.rng.choices(names, weights=[max(0.05, weights[n]) for n in names])[0]]

    def _start_activity(self, now: datetime, act: Activity) -> None:
        self.activity = act
        self.activity_end = now + timedelta(minutes=self.rng.randint(act.min_minutes, act.max_minutes))
        self.home_room = act.room
        self._end_excursion()
        if act.meal:
            self.meals_done.add(act.name)
            self.hunger = min(self.hunger, act.fills)
            self.mood = min(1.0, self.mood + 0.05)  # Essen macht froh

    def _end_excursion(self) -> None:
        self.excursion_room = None
        self.excursion_end = None

    # ------------------------------------------------------------ Speichern
    def _load_plans(self) -> None:
        if not self.plan_file:
            return
        try:
            data = json.loads(self.plan_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception as exc:
            log.warning("Terminplan %s unlesbar (%s), plane neu", self.plan_file, exc)
            return

        def dt(value):
            return None if value is None else datetime.fromisoformat(value).astimezone(self.tz)

        for key, entry in data.items():
            try:
                plan = DayPlan(
                    date.fromisoformat(key),
                    dt(entry["aufwachen"]),
                    dt(entry["schlafen"]),
                    dt(entry.get("nachts_auf")),
                    dt(entry.get("nachts_auf_ende")),
                )
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Terminplan-Eintrag %s ungültig (%s), ignoriere ihn", key, exc)
                continue
            self._plans[plan.day] = plan
        log.info("Terminplan geladen: %d Tage", len(self._plans))

    def save_plans(self) -> None:
        if not self.plan_file:
            return

        def iso(value):
            return None if value is None else value.isoformat()

        data = {
            d.isoformat(): {
                "aufwachen": iso(p.wake),
                "schlafen": iso(p.sleep),
                "nachts_auf": iso(p.night_up_start),
                "nachts_auf_ende": iso(p.night_up_end),
            }
            for d, p in sorted(self._plans.items())
        }
        try:
            self.plan_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.plan_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.plan_file)
        except OSError as exc:
            log.warning("Terminplan konnte nicht gespeichert werden: %s", exc)
