"""Business-day arithmetic for plazos (PLAN.md §9.1).

Two rules are not optional in Mexican practice and both live here:

* the count starts the day after the notification takes effect, never the
  notification day itself;
* when the last day is inhábil the term moves to the next hábil day (prórroga).
"""

from calendar import monthrange
from datetime import date, timedelta

from apps.agenda import calendars

DIAS_HABILES, DIAS_NATURALES, MESES = "dias_habiles", "dias_naturales", "meses"
UNITS = (DIAS_HABILES, DIAS_NATURALES, MESES)


def is_habil(day, closed):
    return day.weekday() < 5 and day not in closed


def _next_habil(day, closed):
    day += timedelta(days=1)
    while not is_habil(day, closed):
        day += timedelta(days=1)
    return day


def _prolapse(day, closed):
    while not is_habil(day, closed):
        day += timedelta(days=1)
    return day


def add_business_days(start, count, closed):
    """`count` hábiles counted from the day after `start`."""
    day = start
    for _ in range(count):
        day = _next_habil(day, closed)
    return day


def add_natural_days(start, count, closed):
    """Calendar days; the calendar only matters for the prórroga on the last one."""
    return _prolapse(start + timedelta(days=count), closed)


def add_months(start, count, closed):
    """Calendar months, clamped to the end of the target month, then prórroga."""
    months = start.year * 12 + start.month - 1 + count
    year, month = divmod(months, 12)
    last = monthrange(year, month + 1)[1]
    return _prolapse(date(year, month + 1, min(start.day, last)), closed)


def due_date(notified_on, value, unit, names=calendars.DEFAULT):
    """The computed due date, or None when the term is still incomplete."""
    if notified_on is None or not value or not unit:
        return None
    closed = calendars.closed(names)
    if unit == DIAS_HABILES:
        return add_business_days(notified_on, value, closed)
    if unit == DIAS_NATURALES:
        return add_natural_days(notified_on, value, closed)
    if unit == MESES:
        return add_months(notified_on, value, closed)
    raise ValueError(f"unknown term unit {unit!r}; known: {', '.join(UNITS)}")
