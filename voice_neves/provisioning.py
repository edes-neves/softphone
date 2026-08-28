"""Auto-provisioning: sincroniza contas/segurança a partir de uma config remota.

Camada pura (sem tkinter/pjsua2), testável. O integrador (app.py) cuida de
agendar a sincronização em thread e aplicar o resultado na configuração.

O servidor de provisioning serve um JSON com o formato:

    {
      "version": 3,
      "accounts": [
        {"user": "100", "server": "sip.exemplo.com", "password": "segredo",
         "forward_unconditional": "", "forward_busy": "",
         "forward_no_answer": "", "forward_no_answer_timeout": 20}
      ],
      "security": {"srtp": "optional", "tls": false},
      "nat": {"ice": true, "stun_server": "stun.exemplo.com"}
    }

Campos de `security`/`nat` seguem a mesma normalização de `config.py`.
"""
import hashlib
import json
import logging
import os
import urllib.error
import urllib.request

from .config import _clean_nat, _clean_security
from .utils import clean_extension, is_valid_extension, is_valid_server

__all__ = [
    "PROVISION_CACHE_FILE",
    "parse_provision",
    "fetch_payload",
    "payload_checksum",
    "ProvisioningManager",
]


def prov_cache_path(data_dir):
    return os.path.join(data_dir, "provision_cache.json")


# Mantido por compatibilidade (constants usa dado por data_dir no runtime).
PROVISION_CACHE_FILE = "provision_cache.json"


def parse_provision(raw):
    """Valida e normaliza um payload de provisioning em contas/security/nat."""
    if not isinstance(raw, dict):
        raise ValueError("Payload de provisioning inválido")

    accounts, seen = [], set()
    for item in raw.get("accounts") or []:
        if not isinstance(item, dict):
            continue
        user = clean_extension(item.get("user", ""))
        server = str(item.get("server", "") or "").strip()
        if not is_valid_extension(user) or not is_valid_server(server):
            logging.warning("Conta provisionada inválida ignorada: %r@%r", user, server)
            continue
        key = f"{user}@{server}"
        if key in seen:
            continue
        seen.add(key)
        try:
            timeout = int(item.get("forward_no_answer_timeout", 20))
        except (TypeError, ValueError):
            timeout = 20
        accounts.append(
            {
                "user": user,
                "server": server,
                "password": str(item.get("password", "") or ""),
                "forward_unconditional": str(item.get("forward_unconditional") or "").strip(),
                "forward_busy": str(item.get("forward_busy") or "").strip(),
                "forward_no_answer": str(item.get("forward_no_answer") or "").strip(),
                "forward_no_answer_timeout": max(5, min(60, timeout)),
            }
        )

    result = {"accounts": accounts}
    sec = raw.get("security")
    nat = raw.get("nat")
    if isinstance(sec, dict):
        result["security"] = _clean_security(sec)
    if isinstance(nat, dict):
        result["nat"] = _clean_nat(nat, {})
    return result


def payload_checksum(payload):
    """Checksum do payload para detectar mudanças entre sincronizações."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fetch_payload(url, timeout=10, auth_user="", auth_pass=""):
    """Baixa e faz parse do payload de provisioning da URL remota.

    Levanta urllib.error.URLError/HTTPError em falha de rede/HTTP ou
    ValueError se o conteúdo não for um dict válido.
    """
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if auth_user:
        import base64

        token = base64.b64encode(f"{auth_user}:{auth_pass}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    return parse_provision(raw)


class ProvisioningManager:
    """Gerencia o ciclo de vida do provisioning com cache local (fallback offline).

    O cache é usado para (a) detectar mudanças sem reaplicar toda vez e
    (b) servir os últimos dados válidos caso o servidor esteja inacessível.
    """

    def __init__(self, cache_file=None):
        self.cache_file = cache_file or PROVISION_CACHE_FILE
        self._cache = self._load_cache()

    def _load_cache(self):
        try:
            with open(self.cache_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        return {}

    def _save_cache(self):
        try:
            os.makedirs(os.path.dirname(self.cache_file) or ".", exist_ok=True)
            tmp = self.cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.cache_file)
        except OSError as e:
            logging.warning("Não foi possível gravar cache de provisioning: %s", e)

    def last_checksum(self):
        return self._cache.get("checksum", "")

    def cached_payload(self):
        payload = self._cache.get("payload")
        return payload if isinstance(payload, dict) else None

    def sync(self, url, auth_user="", auth_pass="", timeout=10):
        """Tenta buscar o provisioning remoto; em falha, usa o cache.

        Retorna (payload, changed, from_cache):
          - payload: dict com 'accounts' (e opcional 'security'/'nat') validados
          - changed: True se diferente do último aplicado
          - from_cache: True se veio do cache (offline)
        """
        from_cache = False
        try:
            payload = parse_provision(fetch_payload(url, timeout, auth_user, auth_pass))
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as e:
            logging.warning("Provisioning indisponível (%s); usando cache", e)
            payload = self.cached_payload()
            from_cache = True
            if payload is None:
                return None, False, True

        checksum = payload_checksum(payload)
        changed = checksum != self.last_checksum()
        self._cache = {"checksum": checksum, "payload": payload}
        self._save_cache()
        return payload, changed, from_cache
