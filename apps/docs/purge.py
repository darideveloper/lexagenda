"""Retention: unfiled inbound media goes at 90 days, and a blob dies by refcount (§10, D18)."""

from datetime import timedelta

from django.db.models import Exists, OuterRef
from django.utils import timezone

from . import storage
from .models import Document, InboundMedia

RETENTION_DAYS = 90


def _document_relpath(document):
    return storage.document_relpath(
        document.case_id, document.sha256, storage.ext_for(document.filename, document.mime)
    )


def _shares_document_blob(document):
    for other in Document.objects.filter(
        is_active=True, case_id=document.case_id, sha256=document.sha256
    ):
        if storage.ext_for(other.filename, other.mime) == storage.ext_for(
            document.filename, document.mime
        ):
            return True
    return False


def release_document(document):
    """Soft-delete a Document; its blob goes only when no sibling still points at it."""
    document.is_active = False
    document.save(update_fields=["is_active", "updated_at"])
    if not _shares_document_blob(document):
        storage.delete(_document_relpath(document))
    return document


def purge_inbound(now=None):
    """Mark and unlink unfiled inbound media older than 90 days; returns how many."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=RETENTION_DAYS)
    filed = Document.objects.filter(media=OuterRef("pk"), is_active=True)
    rows = (
        InboundMedia.objects.annotate(filed=Exists(filed))
        .filter(filed=False, purged_at__isnull=True, created_at__lt=cutoff)
        .order_by("pk")
    )
    purged = 0
    for media in rows:
        media.purged_at = now
        media.save(update_fields=["purged_at"])
        if not _blob_still_referenced(media):
            storage.delete(media.path)
        purged += 1
    return purged


def _blob_still_referenced(media):
    if Document.objects.filter(is_active=True, sha256=media.sha256).exists():
        return True
    return (
        InboundMedia.objects.filter(sha256=media.sha256, purged_at__isnull=True)
        .exclude(pk=media.pk)
        .exists()
    )
