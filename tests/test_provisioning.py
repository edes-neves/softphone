import os

from voice_neves import provisioning


def test_parse_provision_basic():
    raw = {
        "version": 1,
        "accounts": [
            {"user": "100", "server": "sip.ex.com", "password": "p1", "forward_busy": "199"},
            {"user": "200", "server": "sip.ex.com", "password": "p2"},
        ],
        "security": {"srtp": "mandatory"},
        "nat": {"ice": True, "stun_server": "stun.ex.com"},
    }
    payload = provisioning.parse_provision(raw)
    assert len(payload["accounts"]) == 2
    a = payload["accounts"][0]
    assert a["user"] == "100" and a["server"] == "sip.ex.com"
    assert a["password"] == "p1"
    assert a["forward_busy"] == "199"
    assert a["forward_unconditional"] == ""  # default
    assert a["forward_no_answer_timeout"] == 20  # default
    assert payload["security"]["srtp"] == "mandatory"
    assert payload["nat"]["ice"] is True


def test_parse_provision_ignores_invalid_and_duplicates():
    raw = {
        "accounts": [
            {"user": "ok1", "server": "sip.ex.com"},
            {"user": "válido?", "server": "bad host"},  # inválidos: ignorado
            {"user": "ok1", "server": "sip.ex.com"},  # duplicado: ignorado
            {"user": "ok2", "server": "OUTRO.com"},
        ]
    }
    payload = provisioning.parse_provision(raw)
    keys = [(a["user"], a["server"]) for a in payload["accounts"]]
    assert keys == [("ok1", "sip.ex.com"), ("ok2", "OUTRO.com")]


def test_parse_provision_invalid_payload():
    import pytest

    with pytest.raises(ValueError):
        provisioning.parse_provision([1, 2, 3])


def test_payload_checksum_deterministic(tmp_path):
    p1 = provisioning.parse_provision({"accounts": [{"user": "a", "server": "s"}]})
    p2 = provisioning.parse_provision({"accounts": [{"server": "s", "user": "a"}]})
    assert provisioning.payload_checksum(p1) == provisioning.payload_checksum(p2)


def test_provisioning_manager_fallback_cache(monkeypatch, tmp_path):
    cache_file = os.path.join(tmp_path, "provision_cache.json")

    good = provisioning.parse_provision({"accounts": [{"user": "100", "server": "s.ex"}]})

    def fake_fetch(url, timeout=10, auth_user="", auth_pass=""):
        raise OSError("rede fora")

    monkeypatch.setattr(provisioning, "fetch_payload", fake_fetch)

    # primeiro sync sem cache -> None
    m = provisioning.ProvisioningManager(cache_file=cache_file)
    payload, changed, from_cache = m.sync("http://remoto")
    assert payload is None and from_cache is True

    # pré-popula um cache preexistente no disco
    m0 = provisioning.ProvisioningManager(cache_file=cache_file)
    m0._cache = {"checksum": provisioning.payload_checksum(good), "payload": good}
    m0._save_cache()

    # offline: usa o cache do disco; é o último conhecido -> sem mudança, mas há dados
    m2 = provisioning.ProvisioningManager(cache_file=cache_file)
    payload, changed, from_cache = m2.sync("http://remoto")
    assert from_cache is True
    assert payload is not None
    assert payload["accounts"][0]["user"] == "100"
    assert changed is False

    # online com conteúdo diferente -> changed True
    def fake_fetch_new(url, timeout=10, auth_user="", auth_pass=""):
        return {"accounts": [{"user": "200", "server": "s.ex"}]}

    monkeypatch.setattr(provisioning, "fetch_payload", fake_fetch_new)
    payload, changed, from_cache = m2.sync("http://remoto")
    assert from_cache is False
    assert changed is True
    assert payload["accounts"][0]["user"] == "200"
