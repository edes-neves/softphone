import json
import os

from voice_neves import config
from voice_neves.secrets_store import SecretsStore


class FakeSecrets:
    """Substituto minimal do SecretsStore para testar _normalize_accounts."""

    def __init__(self):
        self.store = {}

    def get(self, key, default=None):
        return self.store.get(key, default)

    def set(self, key, value):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


def test_account_key():
    assert config._account_key({"user": "3000", "server": "pbx"}) == "3000@pbx"


def test_default_config_shape():
    sec = FakeSecrets()
    cfg = config._default_config(sec)
    assert cfg["accounts"] == []
    assert cfg["theme"] == "auto"
    assert cfg["auto_answer"] is False
    assert "codecs" in cfg and "audio" in cfg["codecs"]
    assert cfg["security"]["srtp"] == "disabled"
    assert cfg["ldap"]["search_filter"] == "(objectClass=person)"


def test_clean_security_normalizes():
    s = config._clean_security({"srtp": "mandatory", "tls": "true", "srtp_tls_only": 1})
    assert s["srtp"] == "mandatory"
    assert s["tls"] is True
    assert s["srtp_tls_only"] is True
    assert config._clean_security({"srtp": "lixo"})["srtp"] == "disabled"


def test_clean_nat_with_secrets():
    sec = FakeSecrets()
    n = config._clean_nat({"stun_server": "stun.x:3478", "ice": "true"}, sec)
    assert n["stun_server"] == "stun.x:3478"
    assert n["ice"] is True
    assert n["turn_password"] == ""


def test_clean_video_clamps():
    v = config._clean_video({"device": "x", "video_bandwidth": -1, "video_resolution": "hd"})
    assert v["device"] == -1
    assert v["video_bandwidth"] == 0
    assert v["video_resolution"] == "auto"
    assert config._clean_video({})["device"] == -1


def test_clean_ldap_defaults():
    ldap_cfg = config._clean_ldap(None)
    assert ldap_cfg["enabled"] is False
    assert ldap_cfg["attributes"]["name"] == "cn"
    assert ldap_cfg["sync_interval"] >= 60


def test_clean_zrtp():
    z = config._clean_zrtp({"enabled": "true", "sas_required": False})
    assert z["enabled"] is True
    assert z["sas_required"] is False
    assert z["allow_unencrypted"] is True  # default


def test_normalize_accounts_filters_and_stores_passwords():
    sec = FakeSecrets()
    accounts = [
        {"user": "3000", "server": "pbx", "password": "sec"},
        {"user": "a b", "server": "pbx"},          # normalizado para "ab"
        {"user": "3000", "server": "pbx"},          # duplicado -> descartado
        {"user": "4000", "server": "h", "forward_no_answer_timeout": 999},
    ]
    out = config._normalize_accounts(accounts, sec)
    assert [a["user"] for a in out] == ["3000", "ab", "4000"]
    assert sec.get("3000@pbx") == "sec"
    # timeout limitado a [5..60]
    t = next(a for a in out if a["user"] == "4000")["forward_no_answer_timeout"]
    assert t == 60


def test_save_and_load_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "config.json"), raising=False)
    sec = FakeSecrets()
    cfg = config._default_config(sec)
    cfg["accounts"] = [
        {"user": "100", "server": "srv", "forward_no_answer_timeout": 15}
    ]
    cfg["auto_answer"] = True
    config.save_config(cfg)
    assert os.path.isfile(config.CONFIG_FILE)

    loaded = config.load_config(sec)
    assert [a["user"] for a in loaded["accounts"]] == ["100"]
    assert loaded["auto_answer"] is True
    assert loaded["accounts"][0]["forward_no_answer_timeout"] == 15
    # permissao 0600 (verificacao que so existe em POSIX)
    if os.name == "posix":
        assert (os.stat(config.CONFIG_FILE).st_mode & 0o777) == 0o600


def test_load_config_missing_returns_default(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "config.json"), raising=False)
    sec = FakeSecrets()
    cfg = config.load_config(sec)
    assert cfg["accounts"] == []
    assert cfg["theme"] == "auto"


def test_migrate_legacy_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "config.json"), raising=False)
    legacy = str(tmp_path / "sip_config.json")
    with open(legacy, "w", encoding="utf-8") as f:
        json.dump({"accounts": [{"user": "200", "server": "p", "password": "x"}]}, f)
    # LEGACY_CONFIG_FILE eh lido do modulo config
    monkeypatch.setattr(config, "LEGACY_CONFIG_FILE", legacy, raising=False)
    sec = FakeSecrets()
    cfg = config.migrate_legacy_config(sec)
    assert cfg is not None
    assert cfg["accounts"][0]["user"] == "200"
    assert sec.get("200@p") == "x"
    # arquivo legado removido apos migracao
    assert not os.path.exists(legacy)


def test_secrets_store_fallback_roundtrip(tmp_path):
    sec = SecretsStore(service="test_softphone", fallback_file=str(tmp_path / "sec.json"))
    # forca o caminho fallback (ignora keyring do sistema) para determinismo
    sec._keyring = None
    sec._fallback = {}
    assert sec.get("k", "d") == "d"
    sec.set("k", "v")
    assert sec.get("k") == "v"
    # reabre para confirmar persistencia 0600
    sec2 = SecretsStore(service="test_softphone", fallback_file=str(tmp_path / "sec.json"))
    sec2._keyring = None
    assert sec2.get("k") == "v"
    if os.name == "posix":
        assert (os.stat(tmp_path / "sec.json").st_mode & 0o777) == 0o600
    sec.delete("k")
    assert sec.get("k", "gone") == "gone"
