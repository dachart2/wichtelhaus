import random
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from wichtelhaus.config import load_config
from wichtelhaus.sun import SunTimes, in_season, parse_month_day
from wichtelhaus.wichtel import ROOMS, Wichtel, parse_hhmm, random_time_between

TZ = ZoneInfo("Europe/Vienna")
CFG = {"aufwachen": ["06:00", "09:00"], "schlafen": ["20:00", "23:00"], "nachts_aufstehen": 0.5, "ausflug_chance": 0.03}
ROOT = Path(__file__).resolve().parent.parent


def at(d: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(d, time(h, m), tzinfo=TZ)


class WichtelTest(unittest.TestCase):
    def test_random_time_between(self):
        rng = random.Random(1)
        for _ in range(1000):
            t = random_time_between(time(6), time(9), rng)
            self.assertTrue(time(6) <= t <= time(9))
        with self.assertRaises(ValueError):
            random_time_between(time(9), time(6), rng)

    def test_parse_hhmm(self):
        self.assertEqual(parse_hhmm("23:30"), time(23, 30))
        self.assertEqual(parse_hhmm(1410), time(23, 30))  # YAML ohne Anführungszeichen

    def test_rhythm_over_ten_days_incl_dst_change(self):
        events = []
        w = Wichtel(CFG, TZ, rng=random.Random(42), on_event=lambda now, msg: events.append(msg))
        start = datetime(2026, 10, 20, 0, 0, tzinfo=TZ).astimezone(timezone.utc)  # Zeitumstellung 25.10.
        wake_ups = 0
        was_awake = False
        for i in range(10 * 1440):
            now = (start + timedelta(minutes=i)).astimezone(TZ)
            w.step(now)
            self.assertIn(w.room, ROOMS)
            if w.awake:
                self.assertTrue(time(6) <= now.time() < time(23, 56), now)
                self.assertTrue(0 <= w.tiredness <= 1.2)
            if now.time() == time(12, 0):
                self.assertTrue(w.awake, now)
            if now.time() == time(3, 0):
                self.assertFalse(w.awake, now)
            if w.awake and not was_awake:
                wake_ups += 1
            was_awake = w.awake
        self.assertEqual(wake_ups, 10)
        self.assertTrue(any("Ausflug" in e for e in events))
        self.assertTrue(any("Basteln" in e for e in events))


class PlanTest(unittest.TestCase):
    def test_schedule_survives_restart(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            today = date(2026, 11, 24)
            a = Wichtel(CFG, TZ, plan_file=path)
            a.plan_ahead(today)
            b = Wichtel(CFG, TZ, plan_file=path)  # "Neustart"
            for i in range(8):
                d = today + timedelta(days=i)
                pa, pb = a.plan_for(d), b.plan_for(d)
                self.assertEqual((pa.wake, pa.sleep, pa.night_up_start), (pb.wake, pb.sleep, pb.night_up_start))

    def test_really_random(self):
        d = date(2026, 11, 24)
        plans = {(Wichtel(CFG, TZ).plan_for(d).wake, Wichtel(CFG, TZ).plan_for(d).sleep) for _ in range(20)}
        self.assertGreater(len(plans), 1)


class SunTest(unittest.TestCase):
    def setUp(self):
        self.sun = SunTimes(47.86, 16.32, TZ)

    def test_sun_times_plausible(self):
        rise, sset = self.sun.get(date(2026, 12, 21))
        self.assertTrue(time(7, 20) <= rise.time() <= time(7, 50), rise)
        self.assertTrue(time(15, 50) <= sset.time() <= time(16, 15), sset)
        rise, sset = self.sun.get(date(2026, 6, 21))  # Sommerzeit
        self.assertTrue(time(4, 40) <= rise.time() <= time(5, 10), rise)
        self.assertTrue(time(20, 40) <= sset.time() <= time(21, 10), sset)

    def test_dark(self):
        d = date(2026, 12, 21)
        self.assertFalse(self.sun.is_dark(at(d, 12), 30, 30))
        self.assertTrue(self.sun.is_dark(at(d, 18), 30, 30))
        self.assertTrue(self.sun.is_dark(at(d, 6), 30, 30))

    def test_outside_light_until_sunrise(self):
        d = date(2026, 12, 21)
        self.assertFalse(self.sun.outside_light_on(at(d, 12)))
        self.assertTrue(self.sun.outside_light_on(at(d, 18)))
        self.assertTrue(self.sun.outside_light_on(at(d, 3)))

    def test_outside_light_off_at(self):
        d = date(2026, 12, 21)
        self.assertTrue(self.sun.outside_light_on(at(d, 23), time(23, 30)))
        self.assertFalse(self.sun.outside_light_on(at(d, 23, 45), time(23, 30)))
        self.assertFalse(self.sun.outside_light_on(at(d, 3), time(23, 30)))
        self.assertTrue(self.sun.outside_light_on(at(d, 0, 30), time(1, 0)))
        self.assertFalse(self.sun.outside_light_on(at(d, 1, 30), time(1, 0)))


class SeasonTest(unittest.TestCase):
    def test_december_only_until_22(self):
        sun = SunTimes(47.86, 16.32, TZ)
        season = (parse_month_day("01.12."), parse_month_day("31.12."))
        off = time(22, 0)
        self.assertTrue(sun.outside_light_on(at(date(2026, 12, 1), 18), off, season))
        self.assertFalse(sun.outside_light_on(at(date(2026, 12, 1), 22, 5), off, season))
        self.assertFalse(sun.outside_light_on(at(date(2026, 11, 30), 18), off, season))
        self.assertTrue(sun.outside_light_on(at(date(2026, 12, 31), 21, 59), off, season))
        self.assertFalse(sun.outside_light_on(at(date(2027, 1, 1), 18), off, season))

    def test_season_over_new_year(self):
        season = (parse_month_day("15.12."), parse_month_day("06.01."))
        self.assertTrue(in_season(date(2026, 12, 20), season))
        self.assertTrue(in_season(date(2027, 1, 6), season))
        self.assertFalse(in_season(date(2027, 1, 7), season))


class ConfigTest(unittest.TestCase):
    def test_shipped_config_is_valid(self):
        cfg = load_config(ROOT / "config.yaml")
        self.assertEqual(cfg["leds"]["anzahl"], 56)
        self.assertEqual(len(cfg["leds"]["zonen"]), 4)
        self.assertEqual(cfg["laterne"]["pin"], 20)
        self.assertEqual(cfg["aussenlicht"]["pin"], 21)


if __name__ == "__main__":
    unittest.main()
