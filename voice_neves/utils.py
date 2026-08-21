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



def _as_bool(value):
    """Converte valores de config (bool/str/int) em booleano."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


