from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from apps.core import health


class PingTests(TestCase):
    def test_an_unset_check_is_a_no_op(self):
        with patch("apps.core.health.urllib.request.urlopen") as urlopen:
            self.assertFalse(health.ping("work"))

    def test_a_ping_tells_healthchecks_the_run_happened(self):
        with patch.dict("os.environ", {"HEALTHCHECK_WORK_URL": "https://hc-ping.com/abc"}):
            with patch("apps.core.health.urllib.request.urlopen") as urlopen:
                self.assertTrue(health.ping("work"))
        self.assertEqual(urlopen.call_args.args[0], "https://hc-ping.com/abc")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], health.TIMEOUT_SECONDS)

    def test_a_failed_run_pings_the_fail_endpoint(self):
        with patch.dict("os.environ", {"HEALTHCHECK_SWEEP_URL": "https://hc-ping.com/abc"}):
            with patch("apps.core.health.urllib.request.urlopen") as urlopen:
                health.ping("sweep", ok=False)
        self.assertEqual(urlopen.call_args.args[0], "https://hc-ping.com/abc/fail")

    def test_an_unreachable_healthchecks_never_breaks_the_timer(self):
        with patch.dict("os.environ", {"HEALTHCHECK_WORK_URL": "https://hc-ping.com/abc"}):
            with patch("apps.core.health.urllib.request.urlopen", side_effect=OSError("down")):
                self.assertFalse(health.ping("work"))


class WorkTimerPingTests(TestCase):
    def test_the_work_timer_pings_on_a_clean_run(self):
        with patch.dict("os.environ", {"HEALTHCHECK_WORK_URL": "https://hc-ping.com/work"}):
            with patch("apps.core.health.urllib.request.urlopen") as urlopen:
                with patch("apps.assistant.management.commands.work.worker.run_once", return_value=False):
                    call_command("work", stdout=StringIO())
        self.assertEqual(urlopen.call_args.args[0], "https://hc-ping.com/work")

    def test_the_work_timer_pings_fail_when_the_worker_raises(self):
        with patch.dict("os.environ", {"HEALTHCHECK_WORK_URL": "https://hc-ping.com/work"}):
            with patch("apps.core.health.urllib.request.urlopen") as urlopen:
                with patch(
                    "apps.assistant.management.commands.work.worker.run_once",
                    side_effect=RuntimeError("boom"),
                ):
                    with self.assertRaises(RuntimeError):
                        call_command("work", stdout=StringIO())
        self.assertEqual(urlopen.call_args.args[0], "https://hc-ping.com/work/fail")


class OtherTimerPingTests(TestCase):
    def test_the_sweep_timer_pings(self):
        with patch.dict("os.environ", {"HEALTHCHECK_SWEEP_URL": "https://hc-ping.com/sweep"}):
            with patch("apps.core.health.urllib.request.urlopen") as urlopen:
                call_command("sweep", stdout=StringIO())
        self.assertEqual(urlopen.call_args.args[0], "https://hc-ping.com/sweep")

    def test_the_brief_timer_pings(self):
        with patch.dict("os.environ", {"HEALTHCHECK_BRIEF_URL": "https://hc-ping.com/brief"}):
            with patch("apps.core.health.urllib.request.urlopen") as urlopen:
                with patch(
                    "apps.assistant.management.commands.brief.brief.render",
                    return_value="buenos días",
                ):
                    call_command("brief", stdout=StringIO())
        self.assertEqual(urlopen.call_args.args[0], "https://hc-ping.com/brief")

    def test_the_brief_timer_pings_fail_when_it_breaks(self):
        with patch.dict("os.environ", {"HEALTHCHECK_BRIEF_URL": "https://hc-ping.com/brief"}):
            with patch("apps.core.health.urllib.request.urlopen") as urlopen:
                with patch(
                    "apps.assistant.management.commands.brief.brief.render",
                    side_effect=RuntimeError("boom"),
                ):
                    with self.assertRaises(RuntimeError):
                        call_command("brief", stdout=StringIO())
        self.assertEqual(urlopen.call_args.args[0], "https://hc-ping.com/brief/fail")
