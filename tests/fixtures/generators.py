"""Generates the native/scanned PDF and image fixtures extraction tests
need, in memory, instead of committing binary sample files. Fully
deterministic and needs no external fonts or assets — PIL's bundled
default bitmap font renders legibly enough for Tesseract at a large size.
"""

import io

import fitz
from PIL import Image, ImageDraw, ImageFont


def build_native_pdf(text: str) -> bytes:
    """A PDF with a real embedded text layer — the direct-extraction path."""
    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 72), text)
        return doc.tobytes()
    finally:
        doc.close()


def render_text_image(text: str, size: tuple[int, int] = (600, 120)) -> bytes:
    """A PNG with rendered (not embedded) text — no text layer, so
    extraction must go through OCR to read it.
    """
    font = ImageFont.load_default(size=40)
    image = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(image)
    draw.text((10, 10), text, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_scanned_pdf(text: str) -> bytes:
    """A PDF containing only an embedded image of text — no text layer,
    simulating a scanned document. Forces the rasterize + OCR fallback.
    """
    size = (600, 120)
    image_bytes = render_text_image(text, size=size)
    doc = fitz.open()
    try:
        page = doc.new_page(width=size[0], height=size[1])
        page.insert_image(page.rect, stream=image_bytes)
        return doc.tobytes()
    finally:
        doc.close()
