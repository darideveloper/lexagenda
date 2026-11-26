import io

from django.test import TestCase

from apps.docs import extraction


def make_pdf(text=None):
    """A minimal one-page PDF; `text=None` gives a scanned-style page with no text layer."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def make_docx(text):
    import docx

    document = docx.Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_xlsx(rows):
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class ExtractionTests(TestCase):
    def test_pdf_with_a_text_layer_is_indexed(self):
        text, no_layer = extraction.extract(
            "application/pdf", "demanda.pdf", make_pdf("La clausula suelo es nula")
        )

        self.assertIn("clausula suelo", text.lower())
        self.assertFalse(no_layer)

    def test_a_scanned_pdf_is_accepted_and_flagged(self):
        text, no_layer = extraction.extract("application/pdf", "escaneo.pdf", make_pdf())

        self.assertEqual(text.strip(), "")
        self.assertTrue(no_layer)

    def test_docx_reads_paragraphs(self):
        text, no_layer = extraction.extract(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "contrato.docx",
            make_docx("Contrato de arrendamiento"),
        )

        self.assertIn("Contrato de arrendamiento", text)
        self.assertFalse(no_layer)

    def test_xlsx_reads_the_first_sheet(self):
        text, no_layer = extraction.extract(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "honorarios.xlsx",
            make_xlsx([["Concepto", "Importe"], ["Demanda", 15000]]),
        )

        self.assertIn("Demanda", text)
        self.assertIn("15000", text)
        self.assertFalse(no_layer)

    def test_txt_is_read_as_utf8(self):
        text, no_layer = extraction.extract("text/plain", "nota.txt", "Adeudo de rentas".encode())

        self.assertEqual(text, "Adeudo de rentas")
        self.assertFalse(no_layer)

    def test_an_unreadable_mime_returns_no_text_without_crashing(self):
        text, no_layer = extraction.extract("image/jpeg", "foto.jpg", b"\xff\xd8jpeg")

        self.assertEqual(text, "")
        self.assertFalse(no_layer)

    def test_a_corrupt_pdf_does_not_crash(self):
        text, no_layer = extraction.extract("application/pdf", "roto.pdf", b"%PDF-nope")

        self.assertEqual(text, "")
        self.assertTrue(no_layer)

    def test_extraction_follows_the_extension_when_mime_is_missing(self):
        text, _ = extraction.extract("", "nota.txt", b"Hola")

        self.assertEqual(text, "Hola")
