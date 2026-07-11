# Sniffed from the actual bytes rather than trusted from the client-supplied
# Content-Type header, which costs nothing to spoof.
_MAGIC_BYTES: list[tuple[bytes, str]] = [
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
]

EXTENSION_BY_CONTENT_TYPE: dict[str, str] = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


def sniff_content_type(content: bytes) -> str | None:
    for magic, content_type in _MAGIC_BYTES:
        if content.startswith(magic):
            return content_type
    return None
