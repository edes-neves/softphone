import os

import pytest

from voice_neves import updater


class FakeResp:
    """Resposta urlopen simulada que drena o buffer a cada read()."""

    def __init__(self, content, headers=None):
        self._content = content
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n):
        chunk = self._content[:n]
        self._content = self._content[n:]
        return chunk


class FakeReq:
    def __init__(self, *a, **k):
        pass

    def add_header(self, *a):
        pass


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

    def fake_urlopen(req, timeout=10):
        return FakeResp(content)

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


def test_default_download_dir_is_user_downloads():
    assert updater.default_download_dir().endswith("Downloads")


def test_download_to_downloads_with_progress(monkeypatch, tmp_path):
    content = b"x" * (1 << 21)  # 2 MiB
    url = "http://x/download/VoiceNeves-1.0.5.exe"

    monkeypatch.setattr(
        updater.urllib.request, "urlopen",
        lambda req, timeout=10: FakeResp(content, {"Content-Length": str(len(content))}),
    )
    monkeypatch.setattr(updater.urllib.request, "Request", FakeReq)
    monkeypatch.setattr(updater, "default_download_dir", lambda: str(tmp_path))

    seen = []
    path = updater.download_to_downloads(url, on_progress=lambda d, t: seen.append((d, t)))

    assert os.path.dirname(path) == str(tmp_path)
    assert os.path.basename(path) == "VoiceNeves-1.0.5.exe"
    assert os.path.getsize(path) == len(content)
    assert seen[0] == (0, len(content))
    assert seen[-1] == (len(content), len(content))


def test_download_canceled_removes_partial(monkeypatch, tmp_path):
    content = b"x" * 4096
    url = "http://x/download/VoiceNeves-1.0.5.exe"

    monkeypatch.setattr(
        updater.urllib.request, "urlopen",
        lambda req, timeout=10: FakeResp(content),
    )
    monkeypatch.setattr(
        updater.urllib.request, "Request",
        lambda *a, **k: FakeReq(),
    )
    monkeypatch.setattr(updater, "default_download_dir", lambda: str(tmp_path))

    calls = {"n": 0}

    def always_cancel():
        calls["n"] += 1
        return True

    with pytest.raises(updater.DownloadCanceled):
        updater.download_to_downloads(url, cancel_cb=always_cancel)
    assert calls["n"] == 1
    assert not list(tmp_path.iterdir())
