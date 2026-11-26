"""Filing: copy an inbound blob under its case as a Document (§10)."""

from . import storage
from .extraction import extract
from .models import Document, InboundMedia


def file_document(case, media=None, *, filename="", mime="", data=None, source=""):
    """Write the blob under `media/documents/<case>/` and record the Document."""
    if media is not None:
        if data is None:
            blob = storage.abs_path(media.path)
            if not blob.is_file():
                raise ValueError("el archivo ya no está; vuelve a enviarlo")
            data = blob.read_bytes()
        filename = filename or media.filename or "archivo"
        mime = mime or media.mime
        source = source or Document.WHATSAPP
    source = source or Document.DASHBOARD
    data = data or b""

    ext = storage.ext_for(filename, mime)
    storage.write_document(case.pk, data, ext)
    text, no_text_layer = extract(mime, filename, data)
    return Document.objects.create(
        case=case,
        client=case.client,
        filename=filename or f"archivo.{ext}",
        mime=mime,
        size=len(data),
        sha256=storage.sha256_bytes(data),
        extracted_text=text,
        no_text_layer=no_text_layer,
        source=source,
        media=media,
    )


def apply_file_document(args):
    """The `confirm` applier: the stored args carry ids, never a payload."""
    from apps.core.models import Case

    case = Case.objects.get(pk=args["case_id"])
    media = InboundMedia.objects.filter(pk=args.get("media_id")).first()
    if media is None:
        raise ValueError("el archivo ya no está; vuelve a enviarlo")
    document = file_document(case, media)
    text = f"Listo: archivé «{document.filename}» en «{case.reference}»."
    return {"document_id": document.pk}, [], text
