"""Shared restrictions for every user file upload (enrollment proofs and documents).

The template `accept="..."` attribute is client-side only and trivially bypassed,
so the extension whitelist is enforced here on the server too.
"""

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_UPLOAD_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png")
# Leading magic bytes for the allowed types — PDF, JPEG, PNG.
ALLOWED_MAGIC = (b"%PDF", b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")


def upload_error(f):
    """German error message if the upload violates size/type limits, else None."""
    if f.size > MAX_UPLOAD_SIZE:
        return "Die Datei ist zu groß (max. 10 MB)."
    if not f.name.lower().endswith(ALLOWED_UPLOAD_EXTENSIONS):
        return "Ungültiger Dateityp (erlaubt: PDF, JPG, PNG)."
    # Content sniffing: a renamed file (e.g. malware.pdf) must not slip past the
    # extension check. Read the header, then rewind so the view can still .read().
    head = f.read(8)
    f.seek(0)
    if not head.startswith(ALLOWED_MAGIC):
        return "Dateiinhalt passt nicht zum Dateityp (erlaubt: PDF, JPG, PNG)."
    return None
