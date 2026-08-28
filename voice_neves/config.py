"""Carregamento/gravacao e normalizacao da configuracao (camada pura)."""
import json
import logging
import os
import tempfile

from .constants import CONFIG_DIR, CONFIG_FILE, LEGACY_CONFIG_FILE
from .themes import THEMES
from .utils import _as_bool, clean_extension, is_valid_extension, is_valid_server


def _account_key(acc):
    return f"{acc['user']}@{acc['server']}"



def _normalize_accounts(accounts, secrets):
    result, seen = [], set()
    for item in accounts or []:
        if not isinstance(item, dict):
            continue
        user = clean_extension(item.get("user", ""))
        server = str(item.get("server", "") or "").strip()
        if not is_valid_extension(user) or not is_valid_server(server):
            logging.warning("Conta inválida ignorada: %r@%r", user, server)
            continue
        key = f"{user}@{server}"
        if key in seen:
            logging.warning("Conta duplicada ignorada: %s", key)
            continue
        seen.add(key)
        password = item.get("password", "")
        if password:
            secrets.set(key, password)
        try:
            timeout = int(item.get("forward_no_answer_timeout", 20))
        except (TypeError, ValueError):
            timeout = 20
        backup_server = str(item.get("backup_server") or "").strip()
        if backup_server and not is_valid_server(backup_server):
            logging.warning("Servidor de backup inválido para %s: %r", key, backup_server)
            backup_server = ""
        result.append(
            {
                "user": user,
                "server": server,
                "backup_server": backup_server,
                "forward_unconditional": str(item.get("forward_unconditional") or "").strip(),
                "forward_busy": str(item.get("forward_busy") or "").strip(),
                "forward_no_answer": str(item.get("forward_no_answer") or "").strip(),
                "forward_no_answer_timeout": max(5, min(60, timeout)),
            }
        )
    return result



def _clean_security(raw):
    """Normaliza a seção de segurança (TLS/SRTP) da configuração."""
    if not isinstance(raw, dict):
        raw = {}
    srtp = str(raw.get("srtp", "disabled") or "disabled")
    if srtp not in ("disabled", "optional", "mandatory"):
        srtp = "disabled"
    return {
        "tls": _as_bool(raw.get("tls")),
        "tls_ca_file": str(raw.get("tls_ca_file", "") or ""),
        "tls_cert_file": str(raw.get("tls_cert_file", "") or ""),
        "tls_key_file": str(raw.get("tls_key_file", "") or ""),
        "srtp": srtp,
        "srtp_tls_only": _as_bool(raw.get("srtp_tls_only")),
    }



def _clean_nat(raw, secrets):
    """Normaliza a seção NAT/STUN/TURN da configuração."""
    if not isinstance(raw, dict):
        raw = {}
    return {
        "stun_server": str(raw.get("stun_server", "") or ""),
        "ice": _as_bool(raw.get("ice")),
        "turn_enabled": _as_bool(raw.get("turn_enabled")),
        "turn_server": str(raw.get("turn_server", "") or ""),
        "turn_user": str(raw.get("turn_user", "") or ""),
        "turn_password": secrets.get("turn", ""),
    }



def _clean_video(raw):
    """Normaliza a seção de vídeo (câmera) da configuração."""
    if not isinstance(raw, dict):
        raw = {}
    try:
        device = int(raw.get("device", -1))
    except (TypeError, ValueError):
        device = -1
    try:
        bandwidth = max(0, int(raw.get("video_bandwidth", 0)))
    except (TypeError, ValueError):
        bandwidth = 0
    resolution = str(raw.get("video_resolution", "auto") or "auto")
    if resolution not in ("auto", "640x480", "1280x720", "1920x1080"):
        resolution = "auto"
    return {
        "device": device,
        "video_bandwidth": bandwidth,
        "video_resolution": resolution,
    }



def _clean_ldap(raw):
    if not isinstance(raw, dict):
        raw = {}
    attrs = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
    try:
        interval = max(60, int(raw.get("sync_interval", 3600)))
    except (TypeError, ValueError):
        interval = 3600
    return {
        "enabled": _as_bool(raw.get("enabled")),
        "server": str(raw.get("server") or "").strip(),
        "base_dn": str(raw.get("base_dn") or "").strip(),
        "bind_dn": str(raw.get("bind_dn") or "").strip(),
        "search_filter": str(raw.get("search_filter") or "(objectClass=person)").strip(),
        "attributes": {
            "name": str(attrs.get("name") or "cn"),
            "number": str(attrs.get("number") or "telephoneNumber"),
            "server": str(attrs.get("server") or "sipServer"),
        },
        "sync_interval": interval,
        "cache_file": str(raw.get("cache_file") or "ldap_cache.json").strip(),
    }



def _clean_zrtp(raw):
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": _as_bool(raw.get("enabled")),
        "sas_required": _as_bool(raw.get("sas_required", True)),
        "allow_unencrypted": _as_bool(raw.get("allow_unencrypted", True)),
    }



def _clean_provisioning(raw):
    """Normaliza a seção de provisioning (config remota) da configuração."""
    if not isinstance(raw, dict):
        raw = {}
    try:
        interval = max(5, min(1440, int(raw.get("interval_min", 60))))
    except (TypeError, ValueError):
        interval = 60
    return {
        "enabled": _as_bool(raw.get("enabled")),
        "url": str(raw.get("url") or "").strip(),
        "auth_user": str(raw.get("auth_user") or "").strip(),
        "interval_min": interval,
    }


# URL padrão do version.json — publicação automática pelo release.yml: o app
# consulta a URL estável (raw) do arquivo commitado no branch padrão, que é
# atualizado a cada release. O usuário pode trocar por qualquer outra URL.
DEFAULT_UPDATER_URL = "https://raw.githubusercontent.com/edes-neves/softphone/master/version.json"


def _clean_updater(raw):
    """Normaliza a seção de atualização automática da configuração."""
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": _as_bool(raw.get("enabled")),
        "url": str(raw.get("url") or DEFAULT_UPDATER_URL).strip(),
        "auth_user": str(raw.get("auth_user") or "").strip(),
        "check_on_start": _as_bool(raw.get("check_on_start", True)),
    }


def _clean_cti(raw):
    """Normaliza a seção da API/CTI REST (integração externa) da configuração."""
    if not isinstance(raw, dict):
        raw = {}
    try:
        port = int(raw.get("port", 9020))
    except (TypeError, ValueError):
        port = 9020
    if not (1 <= port <= 65535):
        port = 9020
    return {
        "enabled": _as_bool(raw.get("enabled")),
        "port": port,
        "token": str(raw.get("token") or "").strip(),
    }


def _default_config(secrets):
    return {
        "accounts": [],
        "codecs": {"audio": {}, "video": {}},
        "theme": "auto",
        "font": "",
        "ringtone": "",
        "pickup_code": "*8",
        "autoanswer_code": "",
        "dnd_code": "",
        "forward_code": "",
        "auto_answer": False,
        "presence_list": [],
        "publish_presence": False,
        "ldap": _clean_ldap(None),
        "zrtp": _clean_zrtp(None),
        "security": _clean_security(None),
        "nat": _clean_nat(None, secrets),
        "video": _clean_video(None),
        "provisioning": _clean_provisioning(None),
        "updater": _clean_updater(None),
        "cti": _clean_cti(None),
    }



def migrate_legacy_config(secrets):
    if not os.path.exists(LEGACY_CONFIG_FILE):
        return None
    logging.info("Migrando configuração legada: %s", LEGACY_CONFIG_FILE)
    try:
        with open(LEGACY_CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logging.error("Falha ao ler config legada (%s); ignorando", e)
        return None

    accounts = _normalize_accounts(data.get("accounts"), secrets)
    new_config = _default_config(secrets)
    new_config["accounts"] = accounts
    save_config(new_config)
    try:
        os.remove(LEGACY_CONFIG_FILE)
        logging.info("Config legada migrada e removida (%d conta(s)).", len(accounts))
    except OSError as e:
        logging.warning("Não foi possível remover %s: %s", LEGACY_CONFIG_FILE, e)
    return new_config



def load_config(secrets):
    if not os.path.exists(CONFIG_FILE):
        migrated = migrate_legacy_config(secrets)
        if migrated is not None:
            return migrated
        os.makedirs(CONFIG_DIR, exist_ok=True)
        return _default_config(secrets)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        codecs = data.get("codecs")
        if not isinstance(codecs, dict) or not isinstance(codecs.get("audio"), dict):
            codecs = {"audio": {}, "video": {}}
        elif not isinstance(codecs.get("video"), dict):
            codecs["video"] = {}
        theme = data.get("theme")
        if theme != "auto" and theme not in THEMES:
            theme = "auto"
        return {
            "accounts": _normalize_accounts(data.get("accounts"), secrets),
            "codecs": codecs,
            "theme": theme,
            "font": str(data.get("font") or ""),
            "ringtone": data.get("ringtone", ""),
            "pickup_code": str(data.get("pickup_code") or "*8"),
            "autoanswer_code": str(data.get("autoanswer_code") or ""),
            "dnd_code": str(data.get("dnd_code") or ""),
            "forward_code": str(data.get("forward_code") or ""),
            "auto_answer": _as_bool(data.get("auto_answer")),
            "presence_list": [
                str(uri).strip() for uri in (data.get("presence_list") or [])
                if isinstance(uri, str) and str(uri).strip()
            ],
            "publish_presence": _as_bool(data.get("publish_presence")),
            "ldap": _clean_ldap(data.get("ldap")),
            "zrtp": _clean_zrtp(data.get("zrtp")),
            "security": _clean_security(data.get("security")),
            "nat": _clean_nat(data.get("nat"), secrets),
            "video": _clean_video(data.get("video")),
            "provisioning": _clean_provisioning(data.get("provisioning")),
            "updater": _clean_updater(data.get("updater")),
            "cti": _clean_cti(data.get("cti")),
        }
    except Exception as e:
        logging.error("Erro ao ler config (%s); usando configuração vazia", e)
        return _default_config(secrets)



def save_config(data):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
    except OSError as e:
        logging.error("Falha ao criar %s: %s", CONFIG_DIR, e)
        return

    payload = dict(data)
    nat = payload.get("nat")
    if isinstance(nat, dict):
        nat = dict(nat)
        nat.pop("turn_password", None)
        payload["nat"] = nat

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".config-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, CONFIG_FILE)
        os.chmod(CONFIG_FILE, 0o600)
    except OSError as e:
        logging.error("Falha ao gravar config: %s", e)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


