from app.uploads import MAX_UPLOAD_SIZE, upload_error


class _Upload:
    def __init__(self, name, size, head=b"%PDF-1.4"):
        self.name, self.size, self._head = name, size, head

    def read(self, n=None):
        return self._head[:n] if n else self._head

    def seek(self, pos):
        pass


def test_ok():
    assert upload_error(_Upload("scan.PDF", 1000, b"%PDF-1.4")) is None
    assert upload_error(_Upload("photo.jpeg", 1000, b"\xff\xd8\xff\xe0")) is None
    assert upload_error(_Upload("shot.png", 1000, b"\x89PNG\r\n\x1a\n")) is None


def test_too_big():
    assert "groß" in upload_error(_Upload("scan.pdf", MAX_UPLOAD_SIZE + 1))


def test_bad_extension():
    assert "Dateityp" in upload_error(_Upload("malware.exe", 10))
    assert "Dateityp" in upload_error(_Upload("noext", 10))


def test_content_mismatch():
    # Right extension, wrong bytes (renamed executable) is rejected.
    assert "Dateiinhalt" in upload_error(_Upload("malware.pdf", 10, b"MZ\x90\x00"))
