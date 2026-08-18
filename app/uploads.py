"""Shared restrictions for every user file upload (enrollment proofs and documents).

The template `accept="..."` attribute is client-side only and trivially bypassed,
so the extension whitelist is enforced here on the server too.
"""

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_UPLOAD_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png")


def upload_error(f):
    """German error message if the upload violates size/type limits, else None."""
    if f.size > MAX_UPLOAD_SIZE:
        return "Die Datei ist zu groß (max. 10 MB)."
    if not f.name.lower().endswith(ALLOWED_UPLOAD_EXTENSIONS):
        return "Ungültiger Dateityp (erlaubt: PDF, JPG, PNG)."
    return None
