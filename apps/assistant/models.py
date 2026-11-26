from django.db import models
from django.utils import timezone

from apps.core.models import TimeStamped


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


class Proposal(TimeStamped):
    """A write tool stores what it would do; only `confirm` applies it (PLAN.md §5.3, D7)."""

    CHAT, BRIEF = "chat", "brief"
    SOURCES = [(CHAT, "chat"), (BRIEF, "brief")]
    PROPOSED, COMMITTED, CANCELLED, SUPERSEDED, EXPIRED, FAILED, UNDONE = (
        "proposed",
        "committed",
        "cancelled",
        "superseded",
        "expired",
        "failed",
        "undone",
    )
    STATUS = [
        (PROPOSED, "propuesta"),
        (COMMITTED, "aplicada"),
        (CANCELLED, "cancelada"),
        (SUPERSEDED, "sustituida"),
        (EXPIRED, "caducada"),
        (FAILED, "fallida"),
        (UNDONE, "deshecha"),
    ]

    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="proposals")
    steps = models.JSONField(default=list)
    summary = models.TextField()
    outbound_text = models.TextField(blank=True)
    source = models.CharField(max_length=8, choices=SOURCES, default=CHAT)
    status = models.CharField(max_length=10, choices=STATUS, default=PROPOSED)
    expires_at = models.DateTimeField()
    committed_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)
    undo_of = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="undos"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["thread", "status", "expires_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["thread"],
                condition=models.Q(status="proposed"),
                name="one_open_proposal_per_thread",
            )
        ]

    def __str__(self):
        return f"#{self.pk} {self.status}: {self.summary[:40]}"


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
