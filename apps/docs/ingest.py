"""Inbound media: download the gowa file, store it content-addressed, cap at 25 MB (§6.4)."""

import logging
from base64 import b64encode
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from django.conf import settings

from . import storage
from .models import InboundMedia

logger = logging.getLogger(__name__)

MAX_BYTES = 25 * 1024 * 1024
TIMEOUT = 30


class TooLarge(Exception):
    """The file cannot enter: the lawyer already got the refusal line."""

    def __init__(self, size):
        self.size = size
        super().__init__(f"archivo de {size} bytes supera {MAX_BYTES}")


def ingest(wamid, data, mime="", filename=""):
    """Store one inbound file; the same wamid returns the row it already made."""
    existing = InboundMedia.objects.filter(wamid=wamid).first()
    if existing is not None:
        return existing
    if len(data) > MAX_BYTES:
        raise TooLarge(len(data))
    ext = storage.ext_for(filename, mime)
    path = storage.write_inbound(data, ext)
    return InboundMedia.objects.create(
        wamid=wamid,
        path=path,
        mime=mime,
        filename=filename or f"archivo.{ext}",
        size=len(data),
        sha256=storage.sha256_bytes(data),
    )


def download(ref):
    """Fetch a gowa static path (or an absolute URL) without trusting its size."""
    if not ref:
        raise ValueError("media sin ruta")
    if ref.startswith(("http://", "https://")):
        url = ref
    else:
        url = urljoin(settings.GOWA_URL.rstrip("/") + "/", ref.lstrip("/"))
    headers = {}
    if settings.GOWA_BASIC_AUTH:
        token = b64encode(settings.GOWA_BASIC_AUTH.encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    with urlopen(Request(url, headers=headers), timeout=TIMEOUT) as response:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > MAX_BYTES:
            raise TooLarge(int(declared))
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise TooLarge(len(data))
    return data


def ingest_from_gowa(wamid, ref, mime="", filename=""):
    return ingest(wamid, download(ref), mime=mime, filename=filename)
