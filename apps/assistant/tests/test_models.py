from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.assistant.models import AuditLog, Job, Message, Thread


class AssistantModelTests(TestCase):
    def setUp(self):
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")

    def test_wamid_is_the_idempotency_key(self):
        Message.objects.create(thread=self.thread, role="user", text="hola", wamid="wamid-1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Message.objects.create(thread=self.thread, role="user", text="hola", wamid="wamid-1")

    def test_reply_stamp_starts_empty(self):
        msg = Message.objects.create(thread=self.thread, role="user", text="hola", wamid="w-1")
        self.assertIsNone(msg.replied_at)

    def test_job_defaults_to_queued(self):
        job = Job.objects.create(payload={"message_id": 1})
        self.assertEqual(job.status, Job.QUEUED)
        self.assertEqual(job.attempts, 0)
        self.assertEqual(job.kind, Job.INBOUND)

    def test_audit_row(self):
        row = AuditLog.objects.create(thread=self.thread, tool="agenda_today", ok=True)
        self.assertEqual(row.args, {})
        self.assertTrue(row.ok)
