from app.services.extraction import extract_text
from tests.fixtures.generators import build_native_pdf, build_scanned_pdf, render_text_image


def test_extract_text_from_native_pdf() -> None:
    pdf_bytes = build_native_pdf("Hello IntelliExtract native extraction")

    text = extract_text(pdf_bytes, "application/pdf")

    assert "IntelliExtract" in text


def test_extract_text_from_scanned_pdf_falls_back_to_ocr() -> None:
    pdf_bytes = build_scanned_pdf("SCANNED INVOICE")

    text = extract_text(pdf_bytes, "application/pdf")

    assert "SCANNED" in text.upper()


def test_extract_text_from_image_uses_ocr() -> None:
    image_bytes = render_text_image("RECEIPT TOTAL 42")

    text = extract_text(image_bytes, "image/png")

    assert "RECEIPT" in text.upper()
