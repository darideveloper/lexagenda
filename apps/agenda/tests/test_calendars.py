import tempfile
from datetime import date
from pathlib import Path

from django.test import SimpleTestCase

from apps.agenda import calendars


class CalendarDataTests(SimpleTestCase):
    def test_the_four_calendars_load(self):
        loaded = calendars.load_all()
        self.assertEqual(set(loaded), {"federal", "oaj", "hidalgo", "custom"})
        self.assertGreater(len(loaded["federal"].days), 0)

    def test_every_entry_carries_its_source_and_verification(self):
        for calendar in calendars.load_all().values():
            for day in calendar.days:
                self.assertTrue(day.source.startswith("https://"), day)
                self.assertIn(day.verified_on, (None, date(2026, 11, 26)), day)

    def test_default_union_covers_the_three_official_calendars(self):
        union = calendars.closed()
        self.assertIn(date(2026, 2, 5), union)  # oaj: inhábil pero laborable
        self.assertIn(date(2026, 7, 20), union)  # hidalgo vacation
        self.assertNotIn(date(2026, 3, 10), union)

    def test_federal_moves_the_monday_holidays(self):
        federal = calendars.load("federal").holidays(2026)
        self.assertIn(date(2026, 2, 2), federal)
        self.assertNotIn(date(2026, 2, 5), federal)
        self.assertIn(date(2026, 3, 16), federal)
        self.assertNotIn(date(2026, 3, 21), federal)

    def test_hidalgo_carries_the_2026_circular(self):
        hidalgo = calendars.load("hidalgo").holidays(2026)
        for day in (
            date(2026, 2, 2),
            date(2026, 3, 16),
            date(2026, 4, 2),
            date(2026, 4, 3),
            date(2026, 5, 1),
            date(2026, 9, 16),
            date(2026, 11, 2),
            date(2026, 11, 16),
        ):
            self.assertIn(day, hidalgo)
        self.assertIn(date(2026, 7, 16), hidalgo)  # vacations start
        self.assertIn(date(2026, 7, 31), hidalgo)
        self.assertNotIn(date(2026, 7, 15), hidalgo)

    def test_oaj_marks_the_open_but_inhabil_days(self):
        by_date = {day.date: day for day in calendars.load("oaj").days}
        self.assertTrue(by_date[date(2026, 2, 5)].laborable)
        self.assertTrue(by_date[date(2026, 11, 20)].laborable)

    def test_custom_starts_empty(self):
        self.assertEqual(calendars.load("custom").days, ())

    def test_a_day_without_a_source_is_rejected(self):
        path = Path(tempfile.mkdtemp()) / "bad.yaml"
        path.write_text(
            "name: bad\nversion: '1'\ndays:\n  - date: 2026-01-02\n    name: Sin fuente\n"
        )
        with self.assertRaises(calendars.CalendarError):
            calendars.load_file(path)

    def test_version_joins_the_union(self):
        self.assertEqual(calendars.version(), "2026.1")
