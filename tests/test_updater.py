import os

from voice_neves import updater


def test_parse_version_and_is_newer():
    assert updater.parse_version("1.2.0") == (1, 2, 0, 0)
    assert updater.parse_version("v1.2.3") == (1, 2, 3, 0)
    assert updater.parse_version("1.2") == (1, 2, 0, 0)
    assert updater.is_newer("1.2.0", "1.1.9") is True
    assert updater.is_newer("1.1.0", "1.2.0") is False
    assert updater.is_newer("1.2.0", "1.2.0") is False
    assert updater.is_newer("1.10.0", "1.9.9") is True  # comparação numérica, não lexicográfica


def test_parse_version_info():
    info = updater.parse_version_info(
        {"version": "2.0", "url": "https://x/App.AppImage", "sha256": "ABC"}
    )
    assert info["version"] == "2.0"
    assert info["sha256"] == "abc"


def test_parse_version_info_missing_fields():
    import pytest

    with pytest.raises(ValueError):
        updater.parse_version_info({"version": "2.0"})
    with pytest.raises(ValueError):
        updater.parse_version_info({"url": "https://x"})


def test_sha256_file(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello world")
    import hashlib

    assert updater.sha256_file(str(p)) == hashlib.sha256(b"hello world").hexdigest()


def test_download_to_temp_and_checksum(monkeypatch, tmp_path):
    content = b"fake-appimage-content"
    url = "http://x/download/App.AppImage"

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            # Garante EOF: responde o conteúdo uma vez e depois b"" para o loop
            # de download de updater.download_to_temp terminar.
            data = self._buf[:n]
            self._buf = self._buf[n:]
            return data

    class FakeReq:
        def __init__(self, *a, **k):
            pass

        def add_header(self, *a):
            pass

    resp = FakeResp()
    resp._buf = content

    def fake_urlopen(req, timeout=10):
        return resp

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(updater.urllib.request, "Request", FakeReq)

    path = updater.download_to_temp(url, dest_dir=str(tmp_path))
    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == content


def test_updater_integration_fake_check(monkeypatch, tmp_path):
    up = updater.Updater(local_version="1.0.0")

    monkeypatch.setattr(
        updater,
        "fetch_version_info",
        lambda *a, **k: {"version": "1.1.0", "url": "http://x/App.AppImage", "sha256": ""},
    )
    assert up.check("http://x/version.json") is True
    assert up.latest["version"] == "1.1.0"
