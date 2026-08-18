from types import SimpleNamespace

from app.uploads import MAX_UPLOAD_SIZE, upload_error


def _f(name, size):
    return SimpleNamespace(name=name, size=size)


def test_ok():
    assert upload_error(_f("scan.PDF", 1000)) is None
    assert upload_error(_f("photo.jpeg", MAX_UPLOAD_SIZE)) is None


def test_too_big():
    assert "groß" in upload_error(_f("scan.pdf", MAX_UPLOAD_SIZE + 1))


def test_bad_extension():
    assert "Dateityp" in upload_error(_f("malware.exe", 10))
    assert "Dateityp" in upload_error(_f("noext", 10))
