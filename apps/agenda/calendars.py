"""Official calendars as data, never as code (PLAN.md §9.1).

One YAML per calendar under ``config/calendars/``. Every entry names the official
``source`` it was read from and the ``verified_on`` date a human confirmed it, so a
wrong holiday table can be traced instead of becoming a missed filing.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import yaml
from django.conf import settings

CALENDAR_DIR = Path(settings.BASE_DIR) / "config" / "calendars"
DEFAULT = ("federal", "oaj", "hidalgo")
NAMES = DEFAULT + ("custom",)


class CalendarError(Exception):
    """A calendar file is missing or malformed; a wrong table must never load silently."""


@dataclass(frozen=True)
class Day:
    date: date
    name: str
    source: str
    verified_on: date | None = None
    # "Inhábil pero laborable": offices open to the public, still closed to terms.
    laborable: bool = False


@dataclass(frozen=True)
class Calendar:
    name: str
    version: str
    days: tuple[Day, ...]

    def holidays(self, *years):
        return {day.date for day in self.days if not years or day.date.year in years}


def _parse_day(raw, where):
    if not isinstance(raw, dict):
        raise CalendarError(f"{where}: entry is not a mapping: {raw!r}")
    try:
        day, name, source = raw["date"], raw["name"], raw["source"]
    except KeyError as missing:
        raise CalendarError(f"{where}: entry {raw.get('date', '?')} lacks {missing}") from None
    if not isinstance(day, date) or isinstance(day, bool):
        raise CalendarError(f"{where}: {day!r} is not a date (write it YYYY-MM-DD)")
    if not str(source).startswith("https://"):
        raise CalendarError(f"{where}: {day} has no official https source")
    verified_on = raw.get("verified_on")
    if verified_on is not None and not isinstance(verified_on, date):
        raise CalendarError(f"{where}: {day} has a bad verified_on: {verified_on!r}")
    return Day(day, str(name), str(source), verified_on, bool(raw.get("laborable", False)))


def _parse_vacation(raw, where):
    try:
        first, last = raw["from"], raw["to"]
    except (TypeError, KeyError):
        raise CalendarError(f"{where}: a vacation needs from and to: {raw!r}") from None
    if not isinstance(first, date) or not isinstance(last, date) or last < first:
        raise CalendarError(f"{where}: bad vacation range {first!r}..{last!r}")
    base = {"name": f"{raw.get('name', 'Periodo vacacional')} (vacaciones)",
            "source": raw.get("source"), "verified_on": raw.get("verified_on")}
    days = []
    while first <= last:
        days.append(_parse_day({**base, "date": first}, where))
        first += timedelta(days=1)
    return days


def load_file(path):
    """Parse one calendar file. Public so tests and the January ritual can point at a file."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CalendarError(f"{path} is missing") from None
    except yaml.YAMLError as exc:
        raise CalendarError(f"{path}: {exc}") from None
    if not isinstance(raw, dict) or not raw.get("name") or not raw.get("version"):
        raise CalendarError(f"{path}: needs name and version")
    days = [_parse_day(entry, path.name) for entry in raw.get("days") or []]
    for span in raw.get("vacations") or []:
        days.extend(_parse_vacation(span, path.name))
    days.sort(key=lambda day: day.date)
    return Calendar(str(raw["name"]), str(raw["version"]), tuple(days))


@lru_cache(maxsize=None)
def load(name):
    if name not in NAMES:
        raise CalendarError(f"unknown calendar {name!r}; known: {', '.join(NAMES)}")
    return load_file(CALENDAR_DIR / f"{name}.yaml")


def load_all():
    return {name: load(name) for name in NAMES}


def closed(names=DEFAULT):
    """Every date closed to terms: the union of the named calendars."""
    return set().union(*(load(name).holidays() for name in names)) if names else set()


def version(names=DEFAULT):
    """The version a verified deadline is stamped with; per-calendar versions join with /."""
    return "/".join(sorted({load(name).version for name in names}))
