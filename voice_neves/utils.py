"""Funcoes puras / utilitarias (sem tkinter, sem pjsua2)."""
import logging
import os
import re
import sys

from . import platform
from .constants import APP_NAME, DATA_DIR, EXT_RE, SERVER_RE


def resource_path(name):
    """Localiza um recurso empacotado (PyInstaller) ou do diretório do projeto.

    Em desenvolvimento, resolve a partir da raiz do projeto (parent do
    pacote), onde ficam Icone.png, ringtone.wav etc. -- mesmo comportamento
    do softphone.py original, que vivia na raiz. Em bundle (_MEIPASS), usa
    a raiz extraida.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        here = os.path.dirname(os.path.abspath(__file__))  # voice_neves/
        base = os.path.dirname(here)  # raiz do projeto
    return os.path.join(base, name)



def notify_send(title, message, urgency="normal"):
    """Envia uma notificação nativa. Não bloqueia a UI. Delega para `platform`.

    Linux: notify-send. macOS: osascript. Windows: log (pendente toast via
    pywin32/winrt no futuro).
    """
    platform.notify_send(APP_NAME, title, message, urgency)



def is_wayland():
    """Detecta se o app está rodando numa sessão Wayland."""
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return True
    return bool(os.environ.get("WAYLAND_DISPLAY"))



def appindicator_available():
    """Verifica se o backend AppIndicator (necessário para bandeja no Wayland) existe."""
    try:
        import gi  # type: ignore
    except Exception:
        return False
    for version in ("AyatanaAppIndicator3", "AppIndicator3"):
        try:
            gi.require_version(version, "0.1")
            return True
        except Exception:
            continue
    return False



def setup_logging():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        log_file = os.path.join(DATA_DIR, "app.log")
    except OSError as e:
        log_file = None
        logging.warning("Não foi possível criar %s: %s", DATA_DIR, e)

    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )


# =========================
# VALIDAÇÃO / SANITIZAÇÃO
# =========================

def clean_extension(raw):
    """Remove espaços, emojis e caracteres inválidos de um ramal/número."""
    if raw is None:
        return ""
    return re.sub(r"[^0-9A-Za-z_.+*#-]", "", str(raw), flags=re.ASCII)



def is_valid_extension(value):
    return bool(EXT_RE.match(value or ""))



def is_valid_server(value):
    return bool(SERVER_RE.match(value or ""))



def build_sip_target(value, server):
    """Converte número ou URI informado pelo usuário em URI SIP."""
    value = str(value or "").strip()
    if not value:
        return ""
    if value.lower().startswith("sip:"):
        return value
    if "@" in value:
        return f"sip:{value}"
    return f"sip:{value}@{server}" if server else ""


_SIP_IDENTITY_MATCH = re.compile(r"<([^>]+)>")


def extract_sip_identity(text):
    """Extrai (nome_display, numero) de uma identidade/URI SIP de forma robusta.

    Trata formatos comuns de chamada recebida, inclusive quando o "From"
    traz um nome de exibição (chamado de "caller ID"):
      '"João" <sip:3000@pbx;user=phone>'  -> ('João', '3000')
      'João <sip:3000@pbx>'               -> ('João', '3000')
      'sip:3000@pbx;transport=udp'        -> (None, '3000')
      '3000'                              -> (None, '3000')

    Retorna (None, None) quando não é possível extrair um número discável.
    """
    if not text:
        return (None, None)
    s = str(text).strip()
    display = ""

    m = _SIP_IDENTITY_MATCH.search(s)
    if m:
        pre = s[: m.start()].strip().strip('"').strip()
        if pre.lower().startswith(("sip:", "tel:")):
            pre = ""
        display = pre
        s = m.group(1)

    if s.lower().startswith("sip:"):
        s = s[4:]
    elif s.lower().startswith("tel:"):
        s = s[4:]

    s = s.split(";", 1)[0]
    if "@" in s:
        s = s.rsplit("@", 1)[0].strip()
        if s.lower() in ("", "sip", "unknown", ".invalid"):
            s = ""
    num = clean_extension(s)
    if not num and not display:
        return (None, None)
    return (display or None, num or None)



def _as_bool(value):
    """Converte valores de config (bool/str/int) em booleano."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")



# =========================
# MWI (Message Waiting Indicator)
# =========================

_MWI_VOICE_LINE = re.compile(
    r"^\s*Voice-Message\s*:\s*([0-9]+)\s*/\s*([0-9]+)(?:\s*\([^)]*\))?\s*$",
    re.IGNORECASE,
)
_MWI_WAITING_LINE = re.compile(r"^\s*Messages-Waiting\s*:\s*(yes|no)\s*$", re.IGNORECASE)


def parse_mwi_count(message_text):
    """Extrai o número de mensagens novas de um corpo SIP de NOTIFY (RFC 3842).

    O body típico de um NOTIFY de correio de voz traz:

        Message-Account: sip:mailbox@host
        Messages-Waiting: yes
        Voice-Message: 2/5 (0/0)

    Retorna o número de mensagens novas (primeiro campo de "Voice-Message"),
    ou 0 quando "Messages-Waiting: no", ou None caso o corpo não traga
    indicação de mensagens (impossível aplicar/indefinido).
    """
    if not message_text:
        return None
    waiting = None
    voice = None
    try:
        for raw in str(message_text).splitlines():
            m = _MWI_WAITING_LINE.match(raw)
            if m:
                waiting = m.group(1).lower()
                continue
            m = _MWI_VOICE_LINE.match(raw)
            if m:
                new = int(m.group(1))
                total = int(m.group(2))
                voice = {"new": new, "total": total}
    except (TypeError, ValueError):
        return None
    if voice is not None:
        return voice["new"]
    if waiting == "no":
        return 0
    return None


