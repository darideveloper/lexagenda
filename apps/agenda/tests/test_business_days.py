from datetime import date

from django.test import SimpleTestCase

from apps.agenda import business_days, calendars


class DueDateRuleTests(SimpleTestCase):
    def test_the_count_starts_the_day_after_notification(self):
        self.assertEqual(
            business_days.due_date(date(2026, 3, 10), 1, "dias_habiles"), date(2026, 3, 11)
        )

    def test_a_friday_notification_skips_the_inhabil_monday(self):
        self.assertEqual(
            business_days.due_date(date(2026, 3, 13), 1, "dias_habiles"), date(2026, 3, 17)
        )

    def test_the_last_day_prolapses_to_the_next_habil(self):
        # 16 sep 2026 is Independence Day, a Wednesday: the month term moves to Thursday.
        self.assertEqual(
            business_days.due_date(date(2026, 8, 16), 1, "meses"), date(2026, 9, 17)
        )

    def test_natural_days_ignore_the_calendar_but_not_the_prolongation(self):
        # 29 abr + 2 natural days = 1 may, inhábil, so it moves to Monday.
        self.assertEqual(
            business_days.due_date(date(2026, 4, 29), 2, "dias_naturales"), date(2026, 5, 4)
        )

    def test_months_keep_the_end_of_month(self):
        # 31 ene + 1 month = 28 feb, a Saturday: prórroga to Monday.
        self.assertEqual(
            business_days.due_date(date(2026, 1, 31), 1, "meses"), date(2026, 3, 2)
        )

    def test_a_vacation_at_the_end_of_the_term_moves_it(self):
        # Hidalgo vacations 16-31 jul 2026: the fourth hábil day after 10 jul is 3 Aug.
        self.assertEqual(
            business_days.due_date(date(2026, 7, 10), 4, "dias_habiles"), date(2026, 8, 3)
        )

    def test_an_inhabil_pero_laborable_day_does_not_count(self):
        # 5 feb 2026 is open to the public and still closed to terms.
        self.assertEqual(
            business_days.due_date(date(2026, 2, 4), 1, "dias_habiles"), date(2026, 2, 6)
        )

    def test_the_union_is_the_default_and_an_override_narrows_it(self):
        narrow = business_days.due_date(
            date(2026, 2, 4), 1, "dias_habiles", names=("federal",)
        )
        self.assertEqual(narrow, date(2026, 2, 5))

    def test_an_incomplete_term_has_no_computed_date(self):
        self.assertIsNone(business_days.due_date(None, 5, "dias_habiles"))
        self.assertIsNone(business_days.due_date(date(2026, 1, 5), None, "dias_habiles"))

    def test_an_unknown_unit_is_rejected(self):
        with self.assertRaises(ValueError):
            business_days.due_date(date(2026, 1, 5), 5, "semanas")


class HandComputedFixtureTests(SimpleTestCase):
    """Ten terms computed on paper against the 2026 calendars, not against the code.

    Two of them land on special days: the 5 feb "inhábil pero laborable", and the
    Hidalgo vacations (16–31 jul and 17 dic–8 ene 2027).
    """

    FIXTURES = [
        # notified_on, value, unit, expected, the hand calculation
        (date(2026, 10, 30), 20, "dias_habiles", date(2026, 12, 2),
         "18 hábiles of nov after 2/16/20 inhábil, + 1 y 2 dic"),
        (date(2026, 3, 13), 3, "dias_habiles", date(2026, 3, 19),
         "16 mar inhábil: 17, 18, 19"),
        (date(2026, 7, 10), 15, "dias_habiles", date(2026, 8, 18),
         "13–15 jul, then vacations 16–31 jul: 3–18 ago"),
        (date(2026, 4, 29), 4, "dias_naturales", date(2026, 5, 4),
         "30 abr + 1–3 may, last day Sunday and 1 may inhábil: prórroga"),
        (date(2026, 12, 31), 1, "meses", date(2027, 2, 2),
         "31 ene 2027 Sunday, 1 feb in-lieu holiday: prórroga to Tuesday"),
        (date(2026, 11, 2), 6, "meses", date(2027, 5, 3),
         "2 may 2027 Sunday: prórroga to Monday"),
        (date(2026, 12, 1), 10, "dias_habiles", date(2026, 12, 15),
         "2–4, 7–11, 14–15 dic"),
        (date(2026, 12, 15), 3, "dias_habiles", date(2027, 1, 12),
         "16 dic, vacations 17 dic–8 ene, 9–10 weekend, 11 y 12 ene"),
        (date(2026, 2, 4), 1, "dias_habiles", date(2026, 2, 6),
         "5 feb inhábil pero laborable: the term skips it"),
        (date(2026, 4, 30), 2, "dias_habiles", date(2026, 5, 5),
         "1 may inhábil: 4 y 5 may"),
    ]

    def test_the_ten_fixtures_match_the_hand_calculation(self):
        for notified_on, value, unit, expected, note in self.FIXTURES:
            with self.subTest(notified_on=notified_on, unit=unit, note=note):
                self.assertEqual(
                    business_days.due_date(notified_on, value, unit), expected
                )

    def test_no_fixture_falls_on_a_closed_day(self):
        closed = calendars.closed()
        for notified_on, value, unit, expected, _ in self.FIXTURES:
            with self.subTest(expected=expected):
                self.assertTrue(business_days.is_habil(expected, closed), expected)
