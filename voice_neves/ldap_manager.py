"""Consulta opcional de diretorio corporativo LDAP com cache local."""
import json
import logging
import os
import threading

from .config import _clean_ldap
from .constants import DATA_DIR
from .utils import clean_extension

try:
    import ldap as ldap_lib  # type: ignore
except Exception:
    ldap_lib = None

try:
    import ldap3 as ldap3_lib  # type: ignore
except Exception:
    ldap3_lib = None

class LDAPManager:
    """Consulta opcional de diretório corporativo com cache local."""

    def __init__(self, app, config, secrets_store):
        self.app = app
        self.config = _clean_ldap(config)
        self.secrets = secrets_store
        self.cache = []
        self._stop = threading.Event()
        self._thread = None
        self._load_cache()
        if self.config["enabled"]:
            self._thread = threading.Thread(target=self._sync_loop, name="ldap-sync", daemon=True)
            self._thread.start()

    def _cache_path(self):
        path = self.config.get("cache_file") or "ldap_cache.json"
        return path if os.path.isabs(path) else os.path.join(DATA_DIR, path)

    def _load_cache(self):
        try:
            with open(self._cache_path(), encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.cache = data
        except (OSError, ValueError):
            self.cache = []

    def _save_cache(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(self._cache_path(), "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logging.warning("Falha ao salvar cache LDAP: %s", e)

    @staticmethod
    def _value(raw):
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else ""
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace").strip()
        return str(raw or "").strip()

    def _parse(self, attrs):
        names = self.config["attributes"]
        name = self._value(attrs.get(names["name"]))
        number = self._value(attrs.get(names["number"]))
        if not name or not number:
            return None
        return {
            "name": name,
            "number": clean_extension(number),
            "server": self._value(attrs.get(names["server"])),
            "favorite": False,
            "ringtone": "",
            "monitor_presence": False,
            "is_ldap": True,
        }

    def _sync_python_ldap(self):
        if ldap_lib is None:
            raise RuntimeError("python-ldap não está instalado")
        uri = self.config["server"]
        conn = ldap_lib.initialize(uri)
        conn.set_option(ldap_lib.OPT_NETWORK_TIMEOUT, 5)
        password = self.secrets.get("ldap_bind", "")
        conn.simple_bind_s(self.config["bind_dn"], password)
        attrs = list(self.config["attributes"].values())
        rows = conn.search_s(
            self.config["base_dn"], ldap_lib.SCOPE_SUBTREE,
            self.config["search_filter"], attrs,
        )
        result = []
        for _dn, values in rows:
            if isinstance(values, dict):
                contact = self._parse(values)
                if contact:
                    result.append(contact)
        try:
            conn.unbind_s()
        except Exception:
            pass
        return result

    def _sync_ldap3(self):
        if ldap3_lib is None:
            raise RuntimeError("ldap3 não está instalado")
        server = ldap3_lib.Server(self.config["server"], connect_timeout=5, get_info=ldap3_lib.NONE)
        conn = ldap3_lib.Connection(
            server, user=self.config["bind_dn"], password=self.secrets.get("ldap_bind", ""),
            auto_bind=True, receive_timeout=5,
        )
        attrs = list(self.config["attributes"].values())
        conn.search(self.config["base_dn"], self.config["search_filter"], attributes=attrs)
        result = []
        for entry in conn.entries:
            values = {name: entry[name].value for name in attrs if name in entry}
            contact = self._parse(values)
            if contact:
                result.append(contact)
        conn.unbind()
        return result

    def sync(self):
        if not self.config["enabled"]:
            return list(self.cache)
        try:
            if ldap_lib is not None:
                self.cache = self._sync_python_ldap()
            elif ldap3_lib is not None:
                self.cache = self._sync_ldap3()
            else:
                raise RuntimeError("python-ldap/ldap3 não instalado")
            self._save_cache()
            self.app._ui(self.app._update_ldap_ui)
        except Exception as e:
            logging.error("Erro na sincronização LDAP: %s; usando cache", e)
            self.app._ui(self.app.show_toast, "LDAP indisponível; usando cache local")
        return list(self.cache)

    def _sync_loop(self):
        while not self._stop.wait(self.config["sync_interval"]):
            self.sync()

    def search(self, query=""):
        q = str(query or "").strip().lower()
        if not q:
            return list(self.cache)
        return [
            contact for contact in self.cache
            if q in f"{contact.get('name', '')} {contact.get('number', '')} {contact.get('server', '')}".lower()
        ]

    def close(self):
        self._stop.set()


# =========================
# ACCOUNT
# =========================
