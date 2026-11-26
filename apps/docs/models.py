from django.contrib.postgres.search import SearchVectorField
from django.db import models

from apps.core.models import Case, Client, TimeStamped


class InboundMedia(models.Model):
    """A file the lawyer sent over WhatsApp, before it is filed under a case (§6.4)."""

    wamid = models.CharField(max_length=64, unique=True)
    path = models.CharField(max_length=255)
    mime = models.CharField(max_length=80, blank=True)
    filename = models.CharField(max_length=200, blank=True)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64, db_index=True)
    purged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "inbound media"

    def __str__(self):
        return self.filename or self.wamid


class Document(TimeStamped):
    """One filed document; the blob is shared by sha256, so deletion is refcounted (§10)."""

    DASHBOARD, WHATSAPP = "dashboard", "whatsapp"
    SOURCES = [(DASHBOARD, "panel"), (WHATSAPP, "whatsapp")]

    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="documents")
    client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents"
    )
    filename = models.CharField(max_length=200)
    mime = models.CharField(max_length=80, blank=True)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64, db_index=True)
    extracted_text = models.TextField(blank=True)
    no_text_layer = models.BooleanField(default=False)
    search_vector = SearchVectorField(null=True, blank=True)
    source = models.CharField(max_length=10, choices=SOURCES, default=DASHBOARD)
    media = models.ForeignKey(
        InboundMedia, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.filename
