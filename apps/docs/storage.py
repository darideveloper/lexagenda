"""Content-addressed storage for inbound and filed blobs (PLAN.md §10)."""

import hashlib
import os
from pathlib import Path

from django.conf import settings
from django.utils import timezone

SOFT_CAP = 500 * 1024 * 1024
WARN_RATIO = 0.8
INBOUND = "media/inbound"
DOCUMENTS = "media/documents"

MIME_EXT = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/plain": "txt",
    "image/jpeg": "jpg",
    "image/png": "png",
    "audio/ogg": "ogg",
}


def MEDIA_ROOT():
    root = getattr(settings, "MEDIA_ROOT", "") or Path(settings.BASE_DIR) / "media"
    return Path(root)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def ext_for(filename, mime=""):
    """The extension kept on disk: the filename's, else the mime's, else `bin`."""
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if suffix:
        return suffix
    return MIME_EXT.get((mime or "").lower(), "bin")


def today_path(moment=None):
    when = timezone.localdate(moment) if moment else timezone.localdate()
    return f"{when:%Y/%m}"


def inbound_relpath(sha, ext, moment=None):
    return f"{INBOUND}/{today_path(moment)}/{sha}.{ext}"


def document_relpath(case_id, sha, ext):
    return f"{DOCUMENTS}/{case_id}/{sha[:2]}/{sha}.{ext}"


def write(relpath, data):
    """Write one blob; a second write of the same bytes is a no-op."""
    target = abs_path(relpath)
    if target.exists():
        return relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    partial.write_bytes(data)
    os.replace(partial, target)
    return relpath


def write_inbound(data, ext, moment=None):
    sha = sha256_bytes(data)
    return write(inbound_relpath(sha, ext, moment), data)


def write_document(case_id, data, ext):
    sha = sha256_bytes(data)
    return write(document_relpath(case_id, sha, ext), data)


def abs_path(relpath):
    return MEDIA_ROOT() / relpath


def delete(relpath):
    target = abs_path(relpath)
    if not target.is_file():
        return False
    target.unlink()
    return True


def instance_bytes():
    root = MEDIA_ROOT()
    if not root.is_dir():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def cap_ratio():
    return instance_bytes() / SOFT_CAP


def cap_warning():
    return cap_ratio() >= WARN_RATIO
