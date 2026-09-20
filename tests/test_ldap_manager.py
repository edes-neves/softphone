"""Testes do cache LDAP (camada pura, sem servidor LDAP real)."""
from voice_neves.ldap_manager import LDAPManager


class _FakeSecrets:
    def get(self, key, default=None):
        return default

    def set(self, key, value):
        pass

    def delete(self, key):
        pass


def _make_manager(tmp_path):
    cfg = {
        "enabled": False,  # não inicia thread de sync
        "cache_file": "ldap_cache.json",
        "attributes": {"name": "cn", "number": "telephoneNumber", "server": "sipServer"},
    }
    return LDAPManager(None, cfg, _FakeSecrets())


def test_ldap_cache_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr("voice_neves.ldap_manager.DATA_DIR", str(tmp_path), raising=False)
    mgr = _make_manager(tmp_path)
    mgr.cache = [{"name": "Ana", "number": "3000", "server": "", "favorite": False,
                  "ringtone": "", "monitor_presence": False, "is_ldap": True}]
    mgr._save_cache()

    # regravação não deixa temporário no DATA_DIR
    mgr._save_cache()
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".ldap-cache-")]
    assert leftovers == []

    # reabre e confirma persistência e integridade
    mgr2 = _make_manager(tmp_path)
    assert mgr2.cache == mgr.cache


def test_ldap_cache_save_handles_bad_dir():
    # diretório inexistente deve logar e não lançar (gravação tolerante)
    mgr = LDAPManager(
        None,
        {"enabled": False, "cache_file": "/proc/definitivamente-invalido/ldap.json",
         "attributes": {"name": "cn", "number": "telephoneNumber", "server": "sipServer"}},
        _FakeSecrets(),
    )
    mgr._save_cache()  # não deve levantar exceção
