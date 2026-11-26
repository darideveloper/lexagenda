"""Text extraction for the four supported kinds; a scanned PDF is accepted, not OCR'd (§10)."""

import io
import logging

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# A corrupt PDF is a finding, not a traceback; pypdf's reader warning is noise here.
logging.getLogger("pypdf").setLevel(logging.ERROR)


def extract(mime, filename, data):
    """Return (text, no_text_layer). Never raises: a broken file is empty text."""
    mime = (mime or "").lower()
    suffix = (filename or "").rsplit(".", 1)[-1].lower()
    if mime == PDF or suffix == "pdf":
        return _pdf(data)
    if mime == DOCX or suffix == "docx":
        return _docx(data)
    if mime == XLSX or suffix == "xlsx":
        return _xlsx(data)
    if mime == "text/plain" or suffix == "txt":
        return data.decode("utf-8", errors="replace"), False
    return "", False


def _pdf(data):
    from pypdf import PdfReader

    try:
        pages = PdfReader(io.BytesIO(data)).pages
        text = "\n".join(page.extract_text() or "" for page in pages)
    except Exception:
        return "", True
    text = text.strip()
    return text, not text


def _docx(data):
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
        chunks = [paragraph.text for paragraph in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                chunks.append(" · ".join(cell.text for cell in row.cells))
    except Exception:
        return "", False
    return "\n".join(chunk for chunk in chunks if chunk).strip(), False


def _xlsx(data):
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet = workbook.worksheets[0]
        rows = []
        for row in sheet.iter_rows(max_row=200, values_only=True):
            cells = [str(value) for value in row if value is not None]
            if cells:
                rows.append(" · ".join(cells))
    except Exception:
        return "", False
    return "\n".join(rows).strip(), False
