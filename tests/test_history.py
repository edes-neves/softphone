
from voice_neves import history


def test_save_and_load_history_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(history, "HISTORY_FILE", str(tmp_path / "history.json"), raising=False)
    data = [
        {"ts": "01/01/2026 10:00", "label": "Saída para 3000", "kind": "outgoing"},
        {"ts": "01/01/2026 11:00", "label": "Entrada de 4000", "kind": "incoming"},
    ]
    history.save_history(data)
    loaded = history.load_history()
    assert loaded == data


def test_load_history_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_FILE", str(tmp_path / "missing.json"), raising=False)
    assert history.load_history() == []


def test_load_history_filters_malformed(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_FILE", str(tmp_path / "h.json"), raising=False)
    with open(history.HISTORY_FILE, "w", encoding="utf-8") as f:
        f.write('[{"ts": "ok", "label": "x"}, {"ts": "no-label"}]')
    loaded = history.load_history()
    assert len(loaded) == 1
    assert loaded[0]["label"] == "x"
