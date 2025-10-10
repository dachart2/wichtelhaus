"""
improved_test.py
-----------------

This script provides a utility for generating random times within a given
interval, with an example use case for determining when a *Wichtel* (gnome)
should be awake and asleep.  The original script in the `wichtelhaus`
repository returned `datetime.timedelta` objects and imported unused
dependencies.  The version here cleans up the imports, follows PEP 8 naming
conventions, adds type hints and docstrings, and returns proper
`datetime.time` objects with formatted output for readability.
"""

import datetime
import random
from typing import Tuple



def random_time_between(start_str: str, end_str: str) -> datetime.time:
    """Return a random time between two HH:MM strings.

    Args:
        start_str (str): Start time in 'HH:MM' format.
        end_str (str): End time in 'HH:MM' format. Must be later than
            ``start_str`` on the same day.

    Returns:
        datetime.time: A random time between ``start_str`` and ``end_str``.

    Raises:
        ValueError: If ``start_str`` is not strictly before ``end_str``.
    """
    start_dt = datetime.datetime.strptime(start_str, "%H:%M")
    end_dt = datetime.datetime.strptime(end_str, "%H:%M")
    if start_dt >= end_dt:
        raise ValueError(
            f"Die Startzeit {start_str} muss vor der Endzeit {end_str} liegen."
        )
    delta_seconds = int((end_dt - start_dt).total_seconds())
    random_offset = random.randint(0, delta_seconds)
    random_dt = start_dt + datetime.timedelta(seconds=random_offset)
    return random_dt.time()



def get_wichtel_times(
    wach_start: str,
    wach_end: str,
    schlaf_start: str,
    schlaf_end: str,
) -> Tuple[datetime.time, datetime.time]:
    """Determine random wake and sleep times for a Wichtel.

    Args:
        wach_start, wach_end: Interval for active (awake) times.
        schlaf_start, schlaf_end: Interval for inactive (sleep) times.

    Returns:
        Tuple of (wake_time, sleep_time) as datetime.time objects.
    """
    wake_time = random_time_between(wach_start, wach_end)
    sleep_time = random_time_between(schlaf_start, schlaf_end)
    return wake_time, sleep_time



def main() -> None:
    """Run a simple demonstration of the Wichtel time generator."""
    wake_time, sleep_time = get_wichtel_times("06:00", "09:00", "18:00", "23:00")
    print("Wichtel aktiv (wach):", wake_time.strftime("%H:%M"))
    print("Wichtel aktiv (schlaf):", sleep_time.strftime("%H:%M"))



if __name__ == "__main__":
    main()
