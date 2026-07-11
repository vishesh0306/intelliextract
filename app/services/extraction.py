import io

import fitz
import pytesseract
from PIL import Image

from app.core.config import get_settings

# Below this many non-whitespace characters, a PDF page's embedded text
# layer is treated as absent (a scanned page often still has a handful of
# stray characters from watermarks/headers) and OCR takes over instead.
_MIN_NATIVE_TEXT_CHARS = 20

_tesseract_configured = False


def _configure_tesseract() -> None:
    global _tesseract_configured
    if _tesseract_configured:
        return
    cmd = get_settings().tesseract_cmd
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    _tesseract_configured = True


def extract_text(content: bytes, content_type: str | None) -> str:
    """Extract text from an uploaded document's raw bytes.

    PDFs try their embedded text layer first (fast, exact) and only fall
    back to rasterize-and-OCR per page when that layer is missing or
    negligible (a scanned PDF with no text layer). Images always go
    straight to OCR.
    """
    _configure_tesseract()

    if content_type == "application/pdf":
        return _extract_from_pdf(content)
    return _extract_from_image(content)


def _extract_from_pdf(content: bytes) -> str:
    doc = fitz.open(stream=content, filetype="pdf")
    try:
        native_text = "\n".join(page.get_text() for page in doc)
        if len(native_text.strip()) >= _MIN_NATIVE_TEXT_CHARS:
            return native_text

        ocr_text = []
        for page in doc:
            pixmap = page.get_pixmap(dpi=300)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            ocr_text.append(pytesseract.image_to_string(image))
        return "\n".join(ocr_text)
    finally:
        doc.close()


def _extract_from_image(content: bytes) -> str:
    image = Image.open(io.BytesIO(content))
    return pytesseract.image_to_string(image)
