from django.db import models
from django.utils import timezone


class Thread(models.Model):
    channel = models.CharField(max_length=16, default="control")
    jid = models.CharField(max_length=64)
    last_activity_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["channel", "jid"], name="one_thread_per_jid")
        ]

    def __str__(self):
        return f"{self.channel}:{self.jid}"


class Message(models.Model):
    USER, ASSISTANT, SYSTEM, TOOL = "user", "assistant", "system", "tool"
    ROLES = [(USER, "user"), (ASSISTANT, "assistant"), (SYSTEM, "system"), (TOOL, "tool")]

    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLES)
    text = models.TextField(blank=True)
    wamid = models.CharField(max_length=128, unique=True, null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    replied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.text[:40]}"


class Job(models.Model):
    INBOUND, BRIEF_SEND, PURGE = "inbound", "brief_send", "purge"
    KINDS = [(INBOUND, "inbound"), (BRIEF_SEND, "brief_send"), (PURGE, "purge")]
    QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"
    STATUS = [
        (QUEUED, "queued"),
        (RUNNING, "running"),
        (DONE, "done"),
        (FAILED, "failed"),
    ]

    kind = models.CharField(max_length=12, choices=KINDS, default=INBOUND)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=STATUS, default=QUEUED)
    attempts = models.PositiveIntegerField(default=0)
    run_after = models.DateTimeField(default=timezone.now)
    locked_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["run_after", "id"]
        indexes = [models.Index(fields=["status", "run_after"])]

    def __str__(self):
        return f"{self.kind} #{self.pk} {self.status}"


class AuditLog(models.Model):
    thread = models.ForeignKey(
        Thread, on_delete=models.CASCADE, null=True, blank=True, related_name="audit"
    )
    tool = models.CharField(max_length=64)
    args = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    model = models.CharField(max_length=64, blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    ok = models.BooleanField(default=True)
    raw_words = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.tool} ok={self.ok}"
