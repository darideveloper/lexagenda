from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.assistant import worker
from apps.assistant.models import Job, Message, Thread

REPLY = "Buen día, ¿en qué le ayudo?"


class WorkerTests(TestCase):
    def setUp(self):
        self.thread = Thread.objects.create(jid="521771234567@s.whatsapp.net")
        self.inbound = Message.objects.create(
            thread=self.thread, role=Message.USER, text="hola", wamid="w-1"
        )
        self.job = Job.objects.create(payload={"message_id": self.inbound.pk})

    @patch("apps.assistant.worker.send_text")
    @patch("apps.assistant.worker.agent.run", return_value=REPLY)
    def test_claims_runs_sends_and_stamps(self, run, send):
        self.assertTrue(worker.run_once())

        self.inbound.refresh_from_db()
        self.job.refresh_from_db()
        self.assertIsNotNone(self.inbound.replied_at)
        self.assertEqual(self.job.status, Job.DONE)
        self.assertEqual(self.job.attempts, 1)
        run.assert_called_once_with(self.thread, "hola", exclude_pk=self.inbound.pk)
        send.assert_called_once_with(self.thread.jid, REPLY)

    @patch("apps.assistant.worker.send_text")
    @patch("apps.assistant.worker.agent.run", return_value=REPLY)
    def test_a_replied_message_is_never_sent_again(self, run, send):
        self.inbound.replied_at = timezone.now()
        self.inbound.save()

        worker.run_once()

        send.assert_not_called()
        run.assert_not_called()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.DONE)

    @patch("apps.assistant.worker.agent.run", side_effect=RuntimeError("llm caído"))
    def test_a_poison_job_retries_three_times_then_fails(self, run):
        for _ in range(worker.MAX_ATTEMPTS):
            self.assertTrue(worker.run_once())
            self.job.refresh_from_db()
            self.job.run_after = timezone.now() - timedelta(seconds=1)
            self.job.save()

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.FAILED)
        self.assertEqual(self.job.attempts, worker.MAX_ATTEMPTS)
        self.assertIn("llm caído", self.job.error)

    def test_a_job_scheduled_for_later_is_not_claimed(self):
        self.job.run_after = timezone.now() + timedelta(minutes=10)
        self.job.save()

        self.assertFalse(worker.run_once())
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.QUEUED)

    @patch("apps.assistant.worker.send_text")
    @patch("apps.assistant.worker.agent.run", return_value=REPLY)
    def test_the_work_command_drains_the_queue(self, run, send):
        call_command("work", stdout=StringIO())

        self.inbound.refresh_from_db()
        self.assertIsNotNone(self.inbound.replied_at)
        self.assertFalse(Job.objects.filter(status=Job.QUEUED).exists())
