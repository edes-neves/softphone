"""Carregamento/gravacao e normalizacao da configuracao (camada pura)."""
import copy
import json
import logging
import os
import tempfile
import threading

from .constants import CONFIG_DIR, CONFIG_FILE, LEGACY_CONFIG_FILE
from .themes import THEMES
from .utils import _as_bool, clean_extension, is_valid_extension, is_valid_server

# Chaves sensíveis que NUNCA devem ser persistidas em config.json. Cada
# entrada é "secao.chave"; os valores reais vivem somente no cofre (secrets).
SENSITIVE_KEYS = (
    "nat.turn_password",
    "provisioning.auth_pass",
    "cti.token",
    "updater.auth_pass",
    "ldap.bind_password",
)

# Serializa gravações concorrentes: two threads chamando save_config ao mesmo
# tempo não podem truncar/escrever metade e corromper o config.json.
_SAVE_LOCK = threading.Lock()


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
                "phone": str(item.get("phone") or "").strip(),
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




def _clean_provisioning(raw):
    """Normaliza a seção de provisioning (config remota) da configuração.

    A chave canônica é ``sync_interval``, em SEGUNDOS (consumida por app.py).
    ``interval_min`` (minutos) é mantido apenas como leitura legada: quando o
    arquivo em disco só carrega ``interval_min``, o valor é convertido para
    segundos no retorno (e o app continua escrevendo ``sync_interval``).
    """
    if not isinstance(raw, dict):
        raw = {}
    if raw.get("sync_interval") is None and raw.get("interval_min") is not None:
        try:
            # converte minutos → segundos ANTES de aplicar o piso de 60 s
            interval_sec = max(60, int(raw["interval_min"]) * 60)
        except (TypeError, ValueError):
            interval_sec = 3600
    else:
        try:
            interval_sec = max(60, int(raw.get("sync_interval", 3600)))
        except (TypeError, ValueError):
            interval_sec = 3600
    return {
        "enabled": _as_bool(raw.get("enabled")),
        "url": str(raw.get("url") or "").strip(),
        "auth_user": str(raw.get("auth_user") or "").strip(),
        "sync_interval": interval_sec,
        # mantida por compatibilidade com leitores do formato antigo (min)
        "interval_min": interval_sec // 60,
    }


# URL padrão do version.json — publicação automática pelo release.yml: o app
# consulta a URL estável (raw) do arquivo commitado no branch padrão, que é
# atualizado a cada release. O usuário pode trocar por qualquer outra URL.
DEFAULT_UPDATER_URL = "https://raw.githubusercontent.com/edes-neves/softphone/master/version.json"


def _clean_updater(raw):
    """Normaliza a seção de atualização automática da configuração.

    A checagem de atualização é um recurso do menu Configurações → Atualização e
    fica habilitada por padrão: mesmo instalações que salvaram ``enabled: false``
    na UI antiga voltam a verificar (a checagem inicial não depende mais dela).
    """
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": _as_bool(raw.get("enabled", True)),
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


def _clean_keepalive(raw):
    """Normaliza a seção de Keep-Alive UDP (NAT/firewall) da configuração."""
    if not isinstance(raw, dict):
        raw = {}
    try:
        interval = int(raw.get("interval_sec", 15))
    except (TypeError, ValueError):
        interval = 15
    return {
        "enabled": _as_bool(raw.get("enabled", True)),
        "interval_sec": max(1, min(3600, interval)),
    }


def _clean_dtmf(raw):
    """Normaliza a seção de DTMF (método e duração do tom) da configuração.

    ``method`` pode ser ``"rfc2833"`` (pacote de áudio RTP) ou ``"sipinfo"``
    (sinalização SIP INFO). ``duration_ms`` é a duração do tom (padrão 160 ms).
    """
    if not isinstance(raw, dict):
        raw = {}
    method = str(raw.get("method") or "rfc2833")
    if method not in ("rfc2833", "sipinfo"):
        method = "rfc2833"
    try:
        duration = int(raw.get("duration_ms", 160))
    except (TypeError, ValueError):
        duration = 160
    return {
        "method": method,
        "duration_ms": max(80, min(1000, duration)),
    }


def _clean_audio(raw):
    """Normaliza a seção de áudio (AEC, AGC, VAD, ring device).

    Configurações antigas (sem a chave ``audio``) caem nos defaults: o app
    continua exatamente como antes. ``ring_device`` é reservado para uso
    futuro (reproduzir o toque num dispositivo separado do de voz); -1 =
    usar o mesmo da voz.
    """
    if not isinstance(raw, dict):
        raw = {}
    try:
        aec_tail = max(0, min(500, int(raw.get("aec_tail_ms", 200))))
    except (TypeError, ValueError):
        aec_tail = 200
    try:
        ring_device = int(raw.get("ring_device", -1))
    except (TypeError, ValueError):
        ring_device = -1
    return {
        "aec_enabled": _as_bool(raw.get("aec_enabled", True)),
        "aec_tail_ms": aec_tail,
        "agc_capture": _as_bool(raw.get("agc_capture", True)),
        "agc_playback": _as_bool(raw.get("agc_playback", False)),
        "vad": _as_bool(raw.get("vad", True)),
        "ring_device": ring_device,
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
        "security": _clean_security(None),
        "nat": _clean_nat(None, secrets),
        "video": _clean_video(None),
        "audio": _clean_audio(None),
        "provisioning": _clean_provisioning(None),
        "updater": _clean_updater(None),
        "cti": _clean_cti(None),
        "keepalive": _clean_keepalive(None),
        "dtmf": _clean_dtmf(None),
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
        # Migração de segredos legados (configs antigas podiam persistir
        # valores em plaintext): move para o cofre (secrets) e zera no dict
        # que fica em memória para o restante do carregamento.
        raw_prov = data.get("provisioning")
        if isinstance(raw_prov, dict):
            legacy = str(raw_prov.get("auth_pass") or "").strip()
            if legacy:
                secrets.set("provision_auth", legacy)
                raw_prov["auth_pass"] = ""
        raw_cti = data.get("cti")
        if isinstance(raw_cti, dict):
            legacy = str(raw_cti.get("token") or "").strip()
            if legacy:
                secrets.set("cti_token", legacy)
                raw_cti["token"] = ""
        raw_upd = data.get("updater")
        if isinstance(raw_upd, dict):
            legacy = str(raw_upd.get("auth_pass") or "").strip()
            if legacy:
                secrets.set("updater_auth", legacy)
                raw_upd["auth_pass"] = ""
        raw_ldap = data.get("ldap")
        if isinstance(raw_ldap, dict):
            legacy = str(raw_ldap.get("bind_password") or "").strip()
            if legacy:
                secrets.set("ldap_bind", legacy)
                raw_ldap["bind_password"] = ""
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
            "security": _clean_security(data.get("security")),
            "nat": _clean_nat(data.get("nat"), secrets),
            "video": _clean_video(data.get("video")),
            "audio": _clean_audio(data.get("audio")),
            "provisioning": _clean_provisioning(data.get("provisioning")),
            "updater": _clean_updater(data.get("updater")),
            "cti": _clean_cti(data.get("cti")),
            "keepalive": _clean_keepalive(data.get("keepalive")),
            "dtmf": _clean_dtmf(data.get("dtmf")),
        }
    except Exception as e:
        logging.error("Erro ao ler config (%s); usando configuração vazia", e)
        return _default_config(secrets)



def save_config(data):
    # Serializa chamadas concorrentes e opera numa CÓPIA profunda: o dict do
    # chamador nunca é mutado pelos strips de SENSITIVE_KEYS abaixo.
    with _SAVE_LOCK:
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
        except OSError as e:
            logging.error("Falha ao criar %s: %s", CONFIG_DIR, e)
            return

        payload = copy.deepcopy(data)
        for dotted in SENSITIVE_KEYS:
            section, _, key = dotted.partition(".")
            section_data = payload.get(section)
            if isinstance(section_data, dict):
                # segredos nunca vão para disco; vivem somente no cofre
                section_data.pop(key, None)

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


