#!/usr/bin/env python3
"""Softphone SIP com tkinter e pjsua2 (PJSIP)."""

import json
import logging
import os
import queue
import re
import sys
import tempfile
import threading
import tkinter as tk
import tkinter.filedialog as filedialog
import tkinter.font as tkfont
from datetime import datetime
from tkinter import messagebox, ttk

import pjsua2 as pj

APP_NAME = "Voice Neves"
APP_VERSION = "1.0.1"
APP_DEV = "José Edes Neves"
APP_UPDATED = "08/2026"
CONFIG_DIR_NAME = "softphone"
KEYRING_SERVICE = "softphone"

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")),
    CONFIG_DIR_NAME,
)
DATA_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share")),
    CONFIG_DIR_NAME,
)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
SECRETS_FILE = os.path.join(CONFIG_DIR, "secrets.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
LEGACY_CONFIG_FILE = "sip_config.json"

EXT_RE = re.compile(r"^[0-9A-Za-z_.+\-*#]+$")
SERVER_RE = re.compile(r"^[0-9A-Za-z.-]+(:\d{1,5})?$")

RINGTONE_FILE = "ringtone.wav"


def resource_path(name):
    """Localiza um recurso empacotado (PyInstaller) ou do diretório do script."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)

STATE_LABELS = {
    "IDLE": "Disponível",
    "CALLING": "Chamando...",
    "RINGING": "Tocando...",
    "INCOMING": "Chamada recebida!",
    "IN_CALL": "Em chamada",
    "HOLD": "Em espera",
}

# Temas da interface (claro / escuro)
THEMES = {
    "light": {
        "bg": "#F4F6F9",
        "card": "#FFFFFF",
        "border": "#D0D5DD",
        "primary_dark": "#1D4ED8",
        "text": "#1E293B",
        "muted": "#64748B",
        "list_even": "#FFFFFF",
        "list_odd": "#EEF2F7",
        "header": "#2563EB",
        "header_chip": "#1D4ED8",
        "keypad_bg": "#1E293B",
        "keypad_fg": "#FFFFFF",
        "tooltip_bg": "#1F2937",
        "tooltip_fg": "#FFFFFF",
    },
    "dark": {
        "bg": "#111827",
        "card": "#1F2937",
        "border": "#374151",
        "primary_dark": "#60A5FA",
        "text": "#E5E7EB",
        "muted": "#9CA3AF",
        "list_even": "#1F2937",
        "list_odd": "#263344",
        "header": "#1D4ED8",
        "header_chip": "#1E40AF",
        "keypad_bg": "#FFFFFF",
        "keypad_fg": "#1E293B",
        "tooltip_bg": "#374151",
        "tooltip_fg": "#F9FAFB",
    },
}

# Paleta de cores da interface (mutadas por set_theme)
COLOR_BG = THEMES["light"]["bg"]
COLOR_CARD = THEMES["light"]["card"]
COLOR_BORDER = THEMES["light"]["border"]
COLOR_PRIMARY = "#2563EB"
COLOR_PRIMARY_DARK = THEMES["light"]["primary_dark"]
COLOR_SUCCESS = "#16A34A"
COLOR_DANGER = "#DC2626"
COLOR_WARNING = "#F59E0B"
COLOR_TEXT = THEMES["light"]["text"]
COLOR_MUTED = THEMES["light"]["muted"]
COLOR_LIST_EVEN = THEMES["light"]["list_even"]
COLOR_LIST_ODD = THEMES["light"]["list_odd"]
COLOR_HEADER = THEMES["light"]["header"]
COLOR_HEADER_CHIP = THEMES["light"]["header_chip"]
COLOR_KEYPAD_BG = THEMES["light"]["keypad_bg"]
COLOR_KEYPAD_FG = THEMES["light"]["keypad_fg"]
COLOR_TOOLTIP_BG = THEMES["light"]["tooltip_bg"]
COLOR_TOOLTIP_FG = THEMES["light"]["tooltip_fg"]


def set_theme(name):
    """Aplica a paleta de cores do tema, atualizando as globais COLOR_*."""
    global COLOR_BG, COLOR_CARD, COLOR_BORDER, COLOR_PRIMARY_DARK
    global COLOR_TEXT, COLOR_MUTED, COLOR_LIST_EVEN, COLOR_LIST_ODD
    global COLOR_HEADER, COLOR_HEADER_CHIP, COLOR_KEYPAD_BG, COLOR_KEYPAD_FG
    global COLOR_TOOLTIP_BG, COLOR_TOOLTIP_FG
    t = THEMES.get(name, THEMES["light"])
    COLOR_BG = t["bg"]
    COLOR_CARD = t["card"]
    COLOR_BORDER = t["border"]
    COLOR_PRIMARY_DARK = t["primary_dark"]
    COLOR_TEXT = t["text"]
    COLOR_MUTED = t["muted"]
    COLOR_LIST_EVEN = t["list_even"]
    COLOR_LIST_ODD = t["list_odd"]
    COLOR_HEADER = t["header"]
    COLOR_HEADER_CHIP = t["header_chip"]
    COLOR_KEYPAD_BG = t["keypad_bg"]
    COLOR_KEYPAD_FG = t["keypad_fg"]
    COLOR_TOOLTIP_BG = t["tooltip_bg"]
    COLOR_TOOLTIP_FG = t["tooltip_fg"]

# Cor do indicador de estado por estado de chamada
STATUS_COLORS = {
    "IDLE": COLOR_SUCCESS,
    "CALLING": COLOR_PRIMARY,
    "RINGING": COLOR_WARNING,
    "INCOMING": COLOR_DANGER,
    "IN_CALL": COLOR_SUCCESS,
    "HOLD": COLOR_WARNING,
}

# Cor do indicador offline (sem conta logada)
COLOR_OFFLINE = "#5C4033"

CODEC_PRIO_DISABLED = 0
CODEC_PRIO_NORMAL = 128
CODEC_PRIO_BEST = 255
CODEC_PRIO_STEP = 16
G729_CODEC_ID = "G729/8000/1"

FONT_CANDIDATES = ("Segoe UI", "Helvetica", "DejaVu Sans", "Noto Sans", "TkDefaultFont")

_picked_font = None


def pick_font():
    """Retorna a primeira fonte disponível, memorizando o resultado."""
    global _picked_font
    if _picked_font is not None:
        return _picked_font
    families = set(tkfont.families())
    for name in FONT_CANDIDATES:
        if name in families:
            _picked_font = name
            return name
    _picked_font = "TkDefaultFont"
    return _picked_font


class ToolTip:
    """Dica de ferramenta simples que aparece ao passar o mouse sobre um widget."""

    def __init__(self, widget, text, delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _schedule(self, _event=None):
        self._hide()
        self._after_id = self.widget.after(self.delay, self._show)

    def _show(self):
        if self._tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 14
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        self._tip.wm_attributes("-topmost", True)
        tk.Label(
            self._tip,
            text=self.text,
            background=COLOR_TOOLTIP_BG,
            foreground=COLOR_TOOLTIP_FG,
            font=(pick_font(), 9),
            padx=8,
            pady=4,
            justify=tk.LEFT,
        ).pack()

    def _hide(self, _event=None):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


# =========================
# LOGGING
# =========================
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


# =========================
# ARMAZENAMENTO DE SENHAS
# =========================
class SecretsStore:
    """Guarda senhas no keyring do sistema; cai para um arquivo 0600 se indisponível."""

    def __init__(self, service=KEYRING_SERVICE, fallback_file=SECRETS_FILE):
        self.service = service
        self.fallback_file = fallback_file
        self._keyring = None
        self._fallback = {}
        self._init()

    def _init(self):
        try:
            import keyring

            keyring.get_password(self.service, "_probe")
            self._keyring = keyring
        except Exception as e:
            logging.warning("Keyring indisponível (%s); usando arquivo de secrets local", e)
            self._keyring = None

        if os.path.exists(self.fallback_file):
            try:
                with open(self.fallback_file, encoding="utf-8") as f:
                    self._fallback = json.load(f) or {}
            except Exception as e:
                logging.warning("Falha ao ler secrets locais (%s); usando vazio", e)
                self._fallback = {}
        self._secure_file(self.fallback_file)

    @staticmethod
    def _secure_file(path):
        try:
            if os.path.exists(path):
                os.chmod(path, 0o600)
        except OSError as e:
            logging.warning("Não foi possível ajustar permissões de %s: %s", path, e)

    def get(self, key, default=None):
        if self._keyring is not None:
            try:
                value = self._keyring.get_password(self.service, key)
                if value is not None:
                    return value
            except Exception as e:
                logging.warning("Falha ao ler keyring (%s); usando fallback", e)
        return self._fallback.get(key, default)

    def set(self, key, value):
        if self._keyring is not None:
            try:
                self._keyring.set_password(self.service, key, value)
                return
            except Exception as e:
                logging.warning("Falha ao gravar keyring (%s); usando fallback", e)
        self._fallback[key] = value
        self._save_fallback()

    def delete(self, key):
        if self._keyring is not None:
            try:
                self._keyring.delete_password(self.service, key)
            except Exception:
                pass
        if key in self._fallback:
            del self._fallback[key]
            self._save_fallback()

    def _save_fallback(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(self.fallback_file, "w", encoding="utf-8") as f:
                json.dump(self._fallback, f, indent=2)
            self._secure_file(self.fallback_file)
        except OSError as e:
            logging.error("Falha ao gravar secrets locais: %s", e)


# =========================
# CONFIG
# =========================
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
        result.append({"user": user, "server": server})
    return result


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
    new_config = {
        "accounts": accounts,
        "codecs": {"audio": {}, "video": {}},
        "theme": "light",
        "ringtone": "",
    }
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
        return {"accounts": [], "codecs": {"audio": {}, "video": {}}, "theme": "light", "ringtone": ""}
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        codecs = data.get("codecs")
        if not isinstance(codecs, dict) or not isinstance(codecs.get("audio"), dict):
            codecs = {"audio": {}, "video": {}}
        elif not isinstance(codecs.get("video"), dict):
            codecs["video"] = {}
        theme = data.get("theme")
        if theme not in THEMES:
            theme = "light"
        return {
            "accounts": _normalize_accounts(data.get("accounts"), secrets),
            "codecs": codecs,
            "theme": theme,
            "ringtone": data.get("ringtone", ""),
        }
    except Exception as e:
        logging.error("Erro ao ler config (%s); usando configuração vazia", e)
        return {"accounts": [], "codecs": {"audio": {}, "video": {}}, "theme": "light", "ringtone": ""}


def save_config(data):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
    except OSError as e:
        logging.error("Falha ao criar %s: %s", CONFIG_DIR, e)
        return

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".config-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
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


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return [
            h for h in data
            if isinstance(h, dict) and isinstance(h.get("ts"), str) and isinstance(h.get("label"), str)
        ]
    except Exception as e:
        logging.error("Erro ao ler histórico (%s); usando vazio", e)
        return []


def save_history(history):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except OSError as e:
        logging.error("Falha ao gravar histórico: %s", e)


# =========================
# ACCOUNT
# =========================
class MyAccount(pj.Account):
    def __init__(self, app, data):
        super().__init__()
        self.app = app
        self.data = data

    def onRegState(self, prm):
        if prm.code == 200:
            status = "ONLINE"
        elif prm.code in (0, 100):
            status = "REGISTERING"
        else:
            status = "OFFLINE"
        logging.info(
            "Registro de %s@%s: código %s (%s)",
            self.data.get("user"),
            self.data.get("server"),
            prm.code,
            prm.reason or "sem motivo",
        )
        self.app._ui(self.app.update_account_status, self, status)

    def onIncomingCall(self, prm):
        try:
            call = MyCall(self, self.app, prm.callId)
            try:
                remote = call.getInfo().remoteUri
            except Exception:
                remote = prm.rdata.wholeMsg[:80]
            logging.info("Chamada recebida de %s", remote)
            self.app._ui(self.app.on_incoming, call)
        except Exception as e:
            logging.error("Erro ao tratar chamada recebida: %s", e)


# =========================
# CALL
# =========================
class MyCall(pj.Call):
    def __init__(self, acc, app, call_id=pj.PJSUA_INVALID_ID):
        super().__init__(acc, call_id)
        self.acc = acc
        self.app = app

    def onCallState(self, prm):
        self.app._ui(self.app.handle_call_state, self, prm)

    def onCallMediaState(self, prm):
        self.app._ui(self.app.on_call_media_state, self)


# =========================
# BOTÃO COM CANTOS ARREDONDADOS
# =========================
class RoundedButton(tk.Canvas):
    """Botão com cantos arredondados desenhado em um Canvas.

    Compatível com a API usada no app: config(text/bg/fg/state/...), cget e
    gerenciadores de geometria (grid/pack).
    """

    def __init__(
        self, parent, text, command=None, bg=COLOR_PRIMARY, fg="#FFFFFF",
        font=None, padx=10, pady=8, radius=12, cursor="hand2",
    ):
        self._text = text
        self._command = command
        self._bg = bg
        self._fg = fg
        self._font = font or (pick_font(), 10, "bold")
        self._padx = padx
        self._pady = pady
        self._radius = radius
        self._disabled = False
        self._hover = False
        self._focused = False
        self._fill = bg

        try:
            bg_parent = parent["bg"]
        except tk.TclError:
            bg_parent = COLOR_BG
        if not bg_parent:
            bg_parent = COLOR_BG

        w, h = self._requested_size()
        super().__init__(
            parent,
            width=w,
            height=h,
            bg=bg_parent,
            highlightthickness=0,
            borderwidth=0,
            relief="flat",
            cursor=cursor,
            takefocus=True,
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<space>", self._on_click)
        self.bind("<Return>", self._on_click)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Configure>", self._draw)

    def _requested_size(self):
        f = tkfont.Font(font=self._font)
        tw = f.measure(self._text)
        th = f.metrics("linespace")
        return tw + 2 * self._padx + 6, th + 2 * self._pady + 6

    @staticmethod
    def _rounded_points(x1, y1, x2, y2, r):
        return [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]

    def _draw(self, _event=None):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1 or h <= 1:
            w, h = self._requested_size()
        r = min(self._radius, w // 2, h // 2)
        fill = self._bg
        if self._disabled:
            fill = COLOR_MUTED
        elif self._hover:
            fill = self._lighten(fill)
        self._fill = fill
        outline = ""
        if self._focused and not self._disabled:
            outline = self._contrast(fill)
        self.create_polygon(
            self._rounded_points(1, 1, w - 1, h - 1, r),
            smooth=True, fill=fill, outline=outline, width=2,
        )
        self.create_text(w // 2, h // 2, text=self._text, fill=self._fg, font=self._font)

    @staticmethod
    def _lighten(color, amount=0.15):
        try:
            if color and color.startswith("#") and len(color) == 7:
                r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
                r = min(255, int(r + (255 - r) * amount))
                g = min(255, int(g + (255 - g) * amount))
                b = min(255, int(b + (255 - b) * amount))
                return f"#{r:02X}{g:02X}{b:02X}"
        except (ValueError, AttributeError):
            pass
        return color

    @staticmethod
    def _contrast(color):
        """Retorna preto/branco conforme o brilho da cor de fundo."""
        try:
            if color and color.startswith("#") and len(color) == 7:
                r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
                lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
                return "#000000" if lum > 0.6 else "#FFFFFF"
        except (ValueError, AttributeError):
            pass
        return "#FFFFFF"

    def _on_enter(self, _event=None):
        if not self._disabled:
            self._hover = True
            self._draw()

    def _on_leave(self, _event=None):
        self._hover = False
        self._draw()

    def _on_focus_in(self, _event=None):
        self._focused = True
        self._draw()

    def _on_focus_out(self, _event=None):
        self._focused = False
        self._draw()

    def _on_click(self, _event=None):
        if not self._disabled and self._command is not None:
            self._command()

    def configure(self, cnf=None, **kw):
        if isinstance(cnf, dict):
            kw.update(cnf)
        redraw = False
        for k, v in kw.items():
            if k == "text":
                self._text = v
                redraw = True
            elif k in ("bg", "background"):
                self._bg = v
                redraw = True
            elif k in ("fg", "foreground"):
                self._fg = v
                redraw = True
            elif k == "state":
                self._disabled = v == tk.DISABLED
                redraw = True
            elif k == "command":
                self._command = v
            elif k == "font":
                self._font = v
                redraw = True
            elif k == "padx":
                self._padx = v
                redraw = True
            elif k == "pady":
                self._pady = v
                redraw = True
            else:
                super().configure(**{k: v})
        if redraw:
            self._draw()

    config = configure

    def cget(self, key):
        if key == "text":
            return self._text
        if key in ("bg", "background"):
            return self._bg
        if key in ("fg", "foreground"):
            return self._fg
        if key == "state":
            return tk.DISABLED if self._disabled else tk.NORMAL
        if key == "command":
            return self._command
        if key == "font":
            return self._font
        return super().cget(key)


# =========================
# APP
# =========================
class SoftphoneApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("440x800")
        self.root.minsize(420, 790)
        self._base_title = APP_NAME

        try:
            icon = tk.PhotoImage(file=resource_path("Icone.png"))
            self.root.iconphoto(True, icon)
            self._icon = icon
        except Exception as e:
            logging.warning("Não foi possível carregar o ícone da janela: %s", e)

        self._font = pick_font()

        self.endpoint = None
        self.accounts = []
        self.current_call = None
        self.current_audio_media = None
        self.incoming_call = None
        self.calls = {}
        self.held_calls = set()
        self.transfer_win = None
        self._pending_xfer = None
        self._switch_call_ids = []
        self.call_state = "IDLE"
        self.muted = False
        self.volume_out = 5.0
        self.volume_in = 5.0
        self._ringback = None
        self._ringtone = None
        self._ringtone_player = None
        self._test_player = None
        self._test_stop_job = None
        self._answer_blink_on = False
        self._answer_blink_job = None
        self.settings_win = None
        self.codec_win = None
        self.edit_win = None
        self._edit_entry = None

        self._main_tid = threading.get_ident()
        self._ui_queue = queue.Queue()

        self.history = load_history()

        self.config_data = load_config(secrets)

        self.theme_name = self.config_data.get("theme", "light")
        if self.theme_name not in THEMES:
            self.theme_name = "light"
        set_theme(self.theme_name)

        self.pickup_code = (self.config_data.get("pickup_code") or "*8").strip() or "*8"

        self.init_pjsip()
        self.apply_saved_codecs()
        self.setup_ui()
        self.auto_register_accounts()
        self.update_call_ui()
        self.root.after(50, self.loop)

    # =========================
    # PJSIP
    # =========================
    def init_pjsip(self):
        self.endpoint = pj.Endpoint()
        self.endpoint.libCreate()

        ep_cfg = pj.EpConfig()
        ep_cfg.logConfig.level = 5
        ep_cfg.logConfig.consoleLevel = 0
        try:
            ep_cfg.logConfig.filename = os.path.join(DATA_DIR, "pjsua.log")
        except Exception as e:
            logging.warning("Não foi possível definir log do pjsua: %s", e)
        self.endpoint.libInit(ep_cfg)

        try:
            tcfg = pj.TransportConfig()
            tcfg.port = 0
            self.endpoint.transportCreate(pj.PJSIP_TRANSPORT_UDP, tcfg)
        except Exception as e:
            logging.error("Erro ao criar transporte UDP: %s", e)

        self.endpoint.libStart()

    # =========================
    # UI
    # =========================
    def setup_menu(self):
        menubar = tk.Menu(self.root)

        m_arquivo = tk.Menu(menubar, tearoff=0)
        m_arquivo.add_command(label="Deletar Conta", accelerator="Ctrl+Shift+D", command=self.delete_account)
        m_arquivo.add_separator()
        m_arquivo.add_command(label="Sair", accelerator="Ctrl+Q", command=self.close)
        menubar.add_cascade(label="Arquivo", menu=m_arquivo)

        m_editar = tk.Menu(menubar, tearoff=0)
        m_editar.add_command(label="Limpar Campos", command=self.clear_fields)
        m_editar.add_command(label="Mute/Unmute", command=self.toggle_mute)
        menubar.add_cascade(label="Editar", menu=m_editar)

        m_config = tk.Menu(menubar, tearoff=0)
        m_config.add_command(label="Configurações...", command=self.open_settings)
        m_config.add_command(label="Codecs...", command=self.open_codecs)
        menubar.add_cascade(label="Configurações", menu=m_config)

        m_exibir = tk.Menu(menubar, tearoff=0)
        m_exibir.add_command(label="Re-registrar Contas", command=self.auto_register_accounts)
        m_exibir.add_separator()
        self._theme_var = tk.BooleanVar(value=(self.theme_name == "dark"))
        m_exibir.add_checkbutton(
            label="Tema Escuro", variable=self._theme_var, command=self.toggle_theme
        )
        menubar.add_cascade(label="Exibir", menu=m_exibir)

        m_historico = tk.Menu(menubar, tearoff=0)
        m_historico.add_command(label="Ver Histórico", command=self.show_history)
        m_historico.add_command(label="Limpar Histórico", command=self.clear_history)
        menubar.add_cascade(label="Histórico", menu=m_historico)

        menubar.add_command(label="Sobre", command=self.show_about)

        self.root.config(menu=menubar)

        self.root.bind_all("<Control-s>", lambda e: self.open_settings())
        self.root.bind_all("<Control-q>", lambda e: self.close())

    def clear_fields(self):
        self.number.delete(0, tk.END)
        if self.settings_win is not None:
            for entry in (self.user, self.server, self.password):
                entry.delete(0, tk.END)

    def show_about(self):
        messagebox.showinfo(
            "Sobre",
            f"{APP_NAME}\n\n"
            f"Versão: {APP_VERSION}\n"
            f"Desenvolvedor: {APP_DEV}\n"
            f"Última atualização: {APP_UPDATED}",
        )

    def setup_ui(self):
        self.setup_menu()
        self.setup_theme()
        self._build_main_ui()
        self.load_devices()

    def _build_main_ui(self, rebuild=False):
        if rebuild:
            number = self.number.get() if hasattr(self, "number") else ""
            keep = self._selected_account_index()
            for attr in ("header", "body"):
                widget = getattr(self, attr, None)
                if widget is not None:
                    try:
                        widget.destroy()
                    except tk.TclError:
                        pass
            self.setup_header()
            self.setup_body()
            if number:
                self.number.insert(0, number)
            if keep is not None and keep < self.listbox.size():
                self.listbox.selection_set(keep)
            self.btn_mute.config(text="Unmute" if self.muted else "Mute")
            self.set_call_state(self.call_state)
            self.refresh()
            self.update_call_ui()
        else:
            self.setup_header()
            self.setup_body()

    def toggle_theme(self):
        self.theme_name = "dark" if self._theme_var.get() else "light"
        self.config_data["theme"] = self.theme_name
        save_config(self.config_data)
        self.apply_theme(self.theme_name)

    def apply_theme(self, name=None):
        if name is not None:
            self.theme_name = name
        set_theme(self.theme_name)
        self.setup_theme()
        for attr in ("settings_win", "codec_win", "history_win", "edit_win"):
            win = getattr(self, attr, None)
            if win is not None:
                try:
                    win.destroy()
                except tk.TclError:
                    pass
                setattr(self, attr, None)
        self._edit_entry = None
        self._build_main_ui(rebuild=True)

    def _selected_account_index(self):
        sel = self.listbox.curselection()
        return sel[0] if sel else None

    def setup_theme(self):
        style = ttk.Style(self.root)
        available = style.theme_names()
        style.theme_use("clam" if "clam" in available else "default")

        style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT, font=(self._font, 10))

        style.configure("TFrame", background=COLOR_BG)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=(self._font, 10))
        style.configure("Title.TLabel", font=(self._font, 12, "bold"))
        style.configure("Muted.TLabel", foreground=COLOR_MUTED, font=(self._font, 9))

        style.configure(
            "TLabelframe",
            background=COLOR_BG,
            bordercolor=COLOR_BORDER,
            relief="solid",
            borderwidth=1,
            padding=10,
        )
        style.configure(
            "TLabelframe.Label",
            background=COLOR_BG,
            foreground=COLOR_PRIMARY_DARK,
            font=(self._font, 10, "bold"),
        )

        style.configure(
            "TEntry", fieldbackground=COLOR_CARD, foreground=COLOR_TEXT, bordercolor=COLOR_BORDER,
            padding=6, font=(self._font, 10),
        )
        style.configure(
            "TCombobox", fieldbackground=COLOR_CARD, foreground=COLOR_TEXT, bordercolor=COLOR_BORDER,
            padding=4, font=(self._font, 10),
        )
        style.configure(
            "Vertical.TScrollbar", background=COLOR_BORDER, troughcolor=COLOR_BG,
            arrowcolor=COLOR_TEXT, borderwidth=0,
        )

        style.configure(
            "Treeview",
            background=COLOR_CARD,
            fieldbackground=COLOR_CARD,
            foreground=COLOR_TEXT,
            bordercolor=COLOR_BORDER,
            rowheight=28,
            font=(self._font, 10),
        )
        style.map(
            "Treeview",
            background=[("selected", COLOR_PRIMARY)],
            foreground=[("selected", "#FFFFFF")],
        )
        style.configure(
            "Treeview.Heading",
            background=COLOR_CARD,
            foreground=COLOR_TEXT,
            font=(self._font, 10, "bold"),
            relief="flat",
        )
        style.map(
            "Treeview.Heading",
            background=[("active", COLOR_BORDER)],
        )

    def setup_header(self):
        header = tk.Frame(self.root, bg=COLOR_HEADER)
        header.pack(fill=tk.X)
        self.header = header

        tk.Label(
            header,
            text=f"📞  {APP_NAME}",
            bg=COLOR_HEADER,
            fg="#FFFFFF",
            font=(self._font, 13, "bold"),
            padx=14,
            pady=12,
        ).pack(side=tk.LEFT)

        tk.Label(
            header,
            text=f"v{APP_VERSION}",
            bg=COLOR_HEADER_CHIP,
            fg="#FFFFFF",
            font=(self._font, 9),
            padx=8,
            pady=2,
        ).pack(side=tk.LEFT, pady=10)

        status_panel = tk.Frame(header, bg=COLOR_HEADER)
        status_panel.pack(side=tk.RIGHT, padx=14)

        self.status_canvas = tk.Canvas(
            status_panel, width=16, height=16, bg=COLOR_HEADER, highlightthickness=0
        )
        self.status_dot = self.status_canvas.create_oval(2, 2, 14, 14, fill=STATUS_COLORS["IDLE"], outline="")
        self.status_canvas.pack(side=tk.LEFT, padx=(0, 6))

        self.status_label = tk.Label(
            status_panel,
            text=f"Status: {STATE_LABELS['IDLE']}",
            bg=COLOR_HEADER,
            fg="#FFFFFF",
            font=(self._font, 10, "bold"),
        )
        self.status_label.pack(side=tk.LEFT)

    def setup_body(self):
        container = tk.Frame(self.root, bg=COLOR_BG)
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_columnconfigure(0, weight=1)
        self.body = container

        # ===== Contas SIP =====
        acc_frame = ttk.LabelFrame(container, text="Contas SIP")
        acc_frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 6))
        container.grid_rowconfigure(0, weight=1)
        acc_frame.grid_columnconfigure(0, weight=1)

        list_frame = tk.Frame(acc_frame, bg=COLOR_BG)
        list_frame.grid(row=0, column=0, sticky="nsew")
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(
            list_frame,
            height=5,
            yscrollcommand=scrollbar.set,
            bg=COLOR_CARD,
            fg=COLOR_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_PRIMARY,
            selectbackground=COLOR_PRIMARY,
            selectforeground="#FFFFFF",
            activestyle="none",
            exportselection=False,
            font=(self._font, 10),
        )
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ToolTip(self.listbox, "Contas SIP registradas. Selecione uma conta para ligar.")

        acc_btns = tk.Frame(acc_frame, bg=COLOR_BG)
        acc_btns.grid(row=1, column=0, sticky="ew", pady=(8, 4))
        for c in range(2):
            acc_btns.grid_columnconfigure(c, weight=1)

        self.btn_edit = self._styled_button(
            acc_btns, "✏️  Editar conta", self.edit_account, COLOR_WARNING, fg=COLOR_TEXT
        )
        self.btn_edit.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ToolTip(self.btn_edit, "Editar a conta selecionada")

        self.btn_delete = self._styled_button(
            acc_btns, "🗑  Deletar conta", self.delete_account, COLOR_DANGER
        )
        self.btn_delete.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # ===== Discagem =====
        dial_frame = ttk.LabelFrame(container, text="Discagem")
        dial_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        container.grid_rowconfigure(1, weight=2)
        dial_frame.grid_columnconfigure(0, weight=1)

        ttk.Label(dial_frame, text="Número").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        self.number = ttk.Entry(dial_frame)
        self.number.grid(row=0, column=1, sticky="ew", pady=3)
        ToolTip(self.number, "Ramal ou número para discar (ex.: 3000)")
        self.number.bind("<Return>", lambda e: self.make_call())

        keypad = tk.Frame(dial_frame, bg=COLOR_BG)
        keypad.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(8, 4))
        for c in range(3):
            keypad.grid_columnconfigure(c, weight=1)
            keypad.grid_rowconfigure(c, weight=1)
        for i, key in enumerate("123456789*0#"):
            r, c = divmod(i, 3)
            self._styled_button(
                keypad, key, lambda k=key: self.on_keypad_press(k),
                COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG,
            ).grid(row=r, column=c, sticky="nsew", padx=2, pady=2)

        call_btns = tk.Frame(dial_frame, bg=COLOR_BG)
        call_btns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 4))
        for c in range(3):
            call_btns.grid_columnconfigure(c, weight=1)

        self.btn_call = self._styled_button(call_btns, "📞  Ligar", self.make_call, COLOR_SUCCESS)
        self.btn_call.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ToolTip(self.btn_call, "Iniciar chamada para o número informado")

        self.btn_answer = self._styled_button(call_btns, "✅  Atender", self.answer, COLOR_PRIMARY)
        self.btn_answer.grid(row=0, column=1, sticky="ew", padx=4)
        ToolTip(self.btn_answer, "Atender a chamada recebida")

        self.btn_hangup = self._styled_button(call_btns, "📵  Desligar", self.hangup, COLOR_DANGER)
        self.btn_hangup.grid(row=0, column=2, sticky="ew", padx=(4, 0))
        ToolTip(self.btn_hangup, "Encerrar a chamada atual")

        self.btn_mute = self._styled_button(
            dial_frame, "Mute", self.toggle_mute, COLOR_WARNING, fg=COLOR_TEXT
        )
        self.btn_mute.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 4))
        ToolTip(self.btn_mute, "Silenciar / reativar o microfone")

        feature_btns = tk.Frame(dial_frame, bg=COLOR_BG)
        feature_btns.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 4))
        for c in range(3):
            feature_btns.grid_columnconfigure(c, weight=1)

        self.btn_hold = self._styled_button(
            feature_btns, "⏸  Espera", self.toggle_hold, COLOR_WARNING, fg=COLOR_TEXT
        )
        self.btn_hold.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ToolTip(self.btn_hold, "Colocar / retirar a chamada em espera")

        self.btn_transfer = self._styled_button(
            feature_btns, "⇄  Transferir", self.open_transfer, COLOR_PRIMARY
        )
        self.btn_transfer.grid(row=0, column=1, sticky="ew", padx=4)
        ToolTip(self.btn_transfer, "Transferir a chamada para outro ramal (cega ou assistida)")

        self.btn_pickup = self._styled_button(
            feature_btns, "📢  Capturar", self.pickup_call, COLOR_SUCCESS
        )
        self.btn_pickup.grid(row=0, column=2, sticky="ew", padx=(4, 0))
        ToolTip(self.btn_pickup, f"Atender chamada tocando em outro ramal (feature code {self.pickup_code})")

        active_frame = ttk.LabelFrame(dial_frame, text="Chamadas ativas")
        active_frame.grid(row=5, column=0, columnspan=2, sticky="ew", padx=12, pady=(4, 8))
        active_frame.grid_columnconfigure(0, weight=1)
        self.call_switch_box = ttk.Combobox(active_frame, state="readonly")
        self.call_switch_box.grid(row=0, column=0, sticky="ew", padx=(4, 4), pady=4)
        self.btn_alternate = self._styled_button(
            active_frame, "Alternar", self.alternate_call, COLOR_PRIMARY
        )
        self.btn_alternate.grid(row=0, column=1, sticky="ew", padx=(4, 4), pady=4)
        ToolTip(self.btn_alternate, "Alternar para a chamada selecionada acima")

    def _styled_button(self, parent, text, command, color, fg="#FFFFFF"):
        return RoundedButton(
            parent,
            text=text,
            command=command,
            bg=color,
            fg=fg,
            font=(self._font, 10, "bold"),
            padx=10,
            pady=8,
            radius=12,
        )

    def _update_volume_labels(self):
        if self.settings_win is not None:
            self.vol_out_label.config(text=str(int(self.volume_out)))
            self.vol_in_label.config(text=str(int(self.volume_in)))

    # =========================
    # CONFIGURAÇÕES
    # =========================
    def open_settings(self):
        if self.settings_win is not None:
            try:
                self.settings_win.deiconify()
                self.settings_win.lift()
            except tk.TclError:
                self.settings_win = None
        if self.settings_win is None:
            win = tk.Toplevel(self.root)
            win.title("Configurações")
            win.geometry("460x620")
            win.minsize(420, 600)
            win.transient(self.root)
            win.protocol("WM_DELETE_WINDOW", self._close_settings)
            self.settings_win = win
            self._build_settings_ui(win)
            self.load_devices()

    def _close_settings(self):
        if self.settings_win is not None:
            self.settings_win.destroy()
            self.settings_win = None

    def _build_settings_ui(self, win):
        container = ttk.Frame(win, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_columnconfigure(0, weight=1)

        acc_frame = ttk.LabelFrame(container, text="Adicionar conta")
        acc_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        acc_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(acc_frame, text="Servidor").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        self.server = ttk.Entry(acc_frame)
        self.server.grid(row=0, column=1, sticky="ew", pady=3)
        ToolTip(self.server, "Endereço do servidor SIP (ex.: 10.0.0.1 ou pbx.empresa.com.br)")

        ttk.Label(acc_frame, text="Ramal").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        self.user = ttk.Entry(acc_frame)
        self.user.grid(row=1, column=1, sticky="ew", pady=3)
        ToolTip(self.user, "Número do seu ramal")

        ttk.Label(acc_frame, text="Senha").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=3)
        self.password = ttk.Entry(acc_frame, show="*")
        self.password.grid(row=2, column=1, sticky="ew", pady=3)
        ToolTip(self.password, "Senha do ramal (guardada no cofre de senhas do sistema)")

        self.btn_save = self._styled_button(
            acc_frame, "💾  Salvar conta", self.save_account, COLOR_SUCCESS
        )
        self.btn_save.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 4))

        audio_frame = ttk.LabelFrame(container, text="Áudio")
        audio_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        container.grid_rowconfigure(1, weight=1)
        audio_frame.grid_columnconfigure(1, weight=1)

        vol_out_frame = tk.Frame(audio_frame, bg=COLOR_BG)
        vol_out_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=3)
        vol_out_frame.grid_columnconfigure(0, weight=1)
        self.vol_out = tk.Scale(
            vol_out_frame, from_=0, to=10, orient=tk.HORIZONTAL,
            command=lambda v: (self.on_volume_out(v), self._update_volume_labels()),
            bg=COLOR_BG, fg=COLOR_TEXT, troughcolor=COLOR_BORDER,
            highlightthickness=0, activebackground=COLOR_PRIMARY,
        )
        self.vol_out.set(int(self.volume_out))
        self.vol_out.grid(row=0, column=0, sticky="ew")
        self.vol_out_label = tk.Label(
            vol_out_frame, text=str(int(self.volume_out)), bg=COLOR_BG, fg=COLOR_PRIMARY_DARK,
            font=(self._font, 10, "bold"), width=3,
        )
        self.vol_out_label.grid(row=0, column=1, padx=(8, 0))

        ttk.Label(audio_frame, text="Saída").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        self.output_devices = ttk.Combobox(audio_frame, state="readonly")
        self.output_devices.grid(row=1, column=1, sticky="ew", pady=3)
        ToolTip(self.output_devices, "Dispositivo de saída (alto-falante)")

        vol_in_frame = tk.Frame(audio_frame, bg=COLOR_BG)
        vol_in_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=3)
        vol_in_frame.grid_columnconfigure(0, weight=1)
        self.vol_in = tk.Scale(
            vol_in_frame, from_=0, to=10, orient=tk.HORIZONTAL,
            command=lambda v: (self.on_volume_in(v), self._update_volume_labels()),
            bg=COLOR_BG, fg=COLOR_TEXT, troughcolor=COLOR_BORDER,
            highlightthickness=0, activebackground=COLOR_PRIMARY,
        )
        self.vol_in.set(int(self.volume_in))
        self.vol_in.grid(row=0, column=0, sticky="ew")
        self.vol_in_label = tk.Label(
            vol_in_frame, text=str(int(self.volume_in)), bg=COLOR_BG, fg=COLOR_PRIMARY_DARK,
            font=(self._font, 10, "bold"), width=3,
        )
        self.vol_in_label.grid(row=0, column=1, padx=(8, 0))

        ttk.Label(audio_frame, text="Entrada").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=3)
        self.input_devices = ttk.Combobox(audio_frame, state="readonly")
        self.input_devices.grid(row=3, column=1, sticky="ew", pady=3)
        ToolTip(self.input_devices, "Dispositivo de entrada (microfone)")

        dev_btns = tk.Frame(audio_frame, bg=COLOR_BG)
        dev_btns.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        for c in range(2):
            dev_btns.grid_columnconfigure(c, weight=1)

        self.btn_dev_apply = self._styled_button(
            dev_btns, "Aplicar dispositivos", self.apply_devices, COLOR_PRIMARY
        )
        self.btn_dev_apply.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.btn_dev_refresh = self._styled_button(
            dev_btns, "Atualizar lista", self.load_devices, COLOR_MUTED
        )
        self.btn_dev_refresh.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        ttk.Label(audio_frame, text="Toque de chamada").grid(row=5, column=0, sticky="w", padx=(0, 8), pady=3)
        self.ringtone_var = tk.StringVar(value=self._ringtone_display())
        ringtone_box = ttk.Entry(audio_frame, textvariable=self.ringtone_var, state="readonly")
        ringtone_box.grid(row=5, column=1, sticky="ew", pady=3)
        ToolTip(ringtone_box, "Arquivo de som do toque de chamada recebida (WAV). Vazio = toque padrão embutido.")

        ring_btns = tk.Frame(audio_frame, bg=COLOR_BG)
        ring_btns.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(4, 4))
        for c in range(3):
            ring_btns.grid_columnconfigure(c, weight=1)

        self.btn_ring_pick = self._styled_button(
            ring_btns, "Procurar...", self._pick_ringtone, COLOR_PRIMARY
        )
        self.btn_ring_pick.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.btn_ring_test = self._styled_button(
            ring_btns, "Testar", self._test_ringtone, COLOR_MUTED
        )
        self.btn_ring_test.grid(row=0, column=1, sticky="ew", padx=(4, 4))
        self.btn_ring_default = self._styled_button(
            ring_btns, "Padrão", self._reset_ringtone, COLOR_MUTED
        )
        self.btn_ring_default.grid(row=0, column=2, sticky="ew", padx=(4, 0))

    def on_keypad_press(self, digit):
        if self.current_call is not None and self.call_state == "IN_CALL":
            try:
                self.current_call.dialDtmf(digit)
            except Exception as e:
                logging.error("Erro ao enviar DTMF: %s", e)
            return
        self.number.insert(tk.END, digit)

    # =========================
    # CODECS
    # =========================
    def open_codecs(self):
        if self.codec_win is not None:
            try:
                self.codec_win.deiconify()
                self.codec_win.lift()
            except tk.TclError:
                self.codec_win = None
        if self.codec_win is None:
            win = tk.Toplevel(self.root)
            win.title("Configurações de Codecs")
            win.geometry("560x520")
            win.minsize(500, 420)
            win.transient(self.root)
            win.protocol("WM_DELETE_WINDOW", self._close_codecs)
            self.codec_win = win
            self._build_codec_ui(win)
            self.refresh_codec_list()

    def _close_codecs(self):
        if self.codec_win is not None:
            self.codec_win.destroy()
            self.codec_win = None

    def _build_codec_ui(self, win):
        container = ttk.Frame(win, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)
        container.grid_rowconfigure(1, weight=1)

        self._codec_map = {}
        columns = ("estado", "codec", "prioridade")
        for r, title in ((0, "Áudio"), (1, "Vídeo")):
            frame = ttk.LabelFrame(container, text=title)
            frame.grid(row=r, column=0, sticky="nsew", pady=(0, 8))
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(0, weight=1)

            tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse", height=6)
            tree.heading("estado", text="Estado")
            tree.heading("codec", text="Codec")
            tree.heading("prioridade", text="Prioridade")
            tree.column("estado", width=100, anchor="center")
            tree.column("codec", width=330, anchor="w")
            tree.column("prioridade", width=80, anchor="center")
            tree.grid(row=0, column=0, sticky="nsew")
            tree.tag_configure("unavailable", foreground=COLOR_MUTED)
            tree.tag_configure("disabled", foreground=COLOR_DANGER)

            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
            scrollbar.grid(row=0, column=1, sticky="ns")
            tree.configure(yscrollcommand=scrollbar.set)

            if r == 0:
                self.audio_tree = tree
            else:
                self.video_tree = tree

        self.codec_note = ttk.Label(container, text="", style="Muted.TLabel", wraplength=520, justify=tk.LEFT)
        self.codec_note.grid(row=2, column=0, sticky="w", pady=(0, 8))

        btns = tk.Frame(container, bg=COLOR_BG)
        btns.grid(row=3, column=0, sticky="ew")
        for c in range(5):
            btns.grid_columnconfigure(c, weight=1)

        self._styled_button(
            btns, "Ativar", lambda: self._codec_action("enable"), COLOR_SUCCESS
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._styled_button(
            btns, "Desativar", lambda: self._codec_action("disable"), COLOR_DANGER
        ).grid(row=0, column=1, sticky="ew", padx=(4, 4))
        self._styled_button(
            btns, "Prioridade +", lambda: self._codec_action("up"), COLOR_PRIMARY
        ).grid(row=0, column=2, sticky="ew", padx=(4, 4))
        self._styled_button(
            btns, "Prioridade −", lambda: self._codec_action("down"), COLOR_PRIMARY
        ).grid(row=0, column=3, sticky="ew", padx=(4, 4))
        self._styled_button(
            btns, "Atualizar", self.refresh_codec_list, COLOR_MUTED
        ).grid(row=0, column=4, sticky="ew", padx=(4, 0))

    def _insert_codec_row(self, tree, codec_id, desc, priority, unavailable=False):
        if unavailable:
            state = "Indisponível"
            prio_text = "—"
        else:
            state = "Ativo" if (priority or 0) > 0 else "Desativado"
            prio_text = str(priority)
        label = f"{codec_id}  ({desc})" if desc else codec_id
        item = tree.insert("", tk.END, values=(state, label, prio_text))
        if unavailable:
            tree.item(item, tags=("unavailable",))
        elif (priority or 0) <= 0:
            tree.item(item, tags=("disabled",))
        self._codec_map[(id(tree), item)] = (codec_id, unavailable)

    def refresh_codec_list(self):
        if self.codec_win is None:
            return
        for tree, kind, enumerator in (
            (self.audio_tree, "audio", self.endpoint.codecEnum2),
            (self.video_tree, "video", self.endpoint.videoCodecEnum2),
        ):
            tree.delete(*tree.get_children())
            codecs = []
            try:
                codecs = enumerator()
            except Exception as e:
                logging.error("Erro ao listar codecs de %s: %s", kind, e)
            for info in codecs:
                codec_id = getattr(info, "codecId", "") or ""
                priority = getattr(info, "priority", 0)
                desc = getattr(info, "desc", "") or ""
                self._insert_codec_row(tree, codec_id, desc, priority)
            if kind == "audio":
                ids = {(self._codec_map[(id(tree), i)][0]) for i in tree.get_children()}
                g729_avail = any(cid.startswith("G729") for cid in ids)
                if not g729_avail:
                    self._insert_codec_row(tree, G729_CODEC_ID, "G.729 (grátis)", 0, unavailable=True)
                    self.codec_note.config(
                        text="G.729 (grátis) não está compilado neste build do PJSIP. "
                             "Para usá-lo, recompile o PJSIP com suporte ao BCG729 "
                             "(--with-external-bcg729) e refaça o binário."
                    )
                else:
                    self.codec_note.config(text="")

    def _selected_codec(self):
        tree = None
        if self.codec_win is None:
            return None
        if self.audio_tree.selection():
            tree = self.audio_tree
        elif self.video_tree.selection():
            tree = self.video_tree
        if tree is None:
            return None
        item = tree.selection()[0]
        return self._codec_map.get((id(tree), item))

    def _set_codec_priority(self, kind, codec_id, priority):
        try:
            if kind == "video":
                self.endpoint.videoCodecSetPriority(codec_id, priority)
            else:
                self.endpoint.codecSetPriority(codec_id, priority)
            logging.info("Prioridade do codec %s (%s) ajustada para %d", codec_id, kind, priority)
            return True
        except Exception as e:
            logging.error("Falha ao ajustar prioridade do codec %s: %s", codec_id, e)
            messagebox.showerror("Codec", f"Não foi possível ajustar o codec {codec_id}:\n{e}")
            return False

    def _read_codec_priority(self, kind, codec_id):
        try:
            enumerator = self.endpoint.videoCodecEnum2 if kind == "video" else self.endpoint.codecEnum2
            for info in enumerator():
                if (getattr(info, "codecId", "") or "") == codec_id:
                    return getattr(info, "priority", 0)
        except Exception as e:
            logging.error("Erro ao ler prioridade do codec %s: %s", codec_id, e)
        return None

    def _codec_action(self, action):
        info = self._selected_codec()
        if info is None:
            return
        codec_id, unavailable = info
        if unavailable:
            messagebox.showinfo(
                "G.729 (grátis)",
                "O codec G.729 (grátis) não está compilado neste build do PJSIP.\n\n"
                "Para ativá-lo é preciso recompilar o PJSIP com suporte ao BCG729 "
                "(--with-external-bcg729) e gerar o binário novamente.",
            )
            return
        kind = "video" if self.video_tree.selection() else "audio"
        saved = self.config_data.setdefault("codecs", {"audio": {}, "video": {}}).setdefault(kind, {})
        current = saved.get(codec_id)
        if current is None:
            current = self._read_codec_priority(kind, codec_id)
        if current is None:
            current = CODEC_PRIO_NORMAL

        if action == "enable":
            new = current if current > 0 else CODEC_PRIO_NORMAL
        elif action == "disable":
            new = CODEC_PRIO_DISABLED
        elif action == "up":
            base = current if current > 0 else CODEC_PRIO_NORMAL
            new = min(CODEC_PRIO_BEST, base + CODEC_PRIO_STEP)
        elif action == "down":
            base = current if current > 0 else CODEC_PRIO_NORMAL
            new = max(CODEC_PRIO_DISABLED, base - CODEC_PRIO_STEP)
        else:
            return

        if self._set_codec_priority(kind, codec_id, new):
            self.config_data["codecs"][kind][codec_id] = new
            save_config(self.config_data)
        self.refresh_codec_list()

    def apply_saved_codecs(self):
        codecs = self.config_data.get("codecs", {})
        for kind in ("audio", "video"):
            for codec_id, priority in (codecs.get(kind) or {}).items():
                if not isinstance(priority, int):
                    continue
                try:
                    if kind == "video":
                        self.endpoint.videoCodecSetPriority(codec_id, priority)
                    else:
                        self.endpoint.codecSetPriority(codec_id, priority)
                    logging.info("Codec %s (%s) aplicado com prioridade %d", codec_id, kind, priority)
                except Exception as e:
                    logging.warning("Não foi possível aplicar o codec %s (%s): %s", codec_id, kind, e)

    # =========================
    # CONTAS
    # =========================
    def save_account(self):
        if self.settings_win is None:
            messagebox.showinfo("Configurações", "Abra Configurações > Contas para adicionar uma conta.")
            return
        user = clean_extension(self.user.get())
        server = self.server.get().strip()
        password = self.password.get()

        if not is_valid_extension(user):
            messagebox.showerror("Erro", "Ramal inválido (use apenas letras, números, _ . + -).")
            return
        if not is_valid_server(server):
            messagebox.showerror("Erro", "Servidor inválido.")
            return

        key = f"{user}@{server}"
        existing = next(
            (a for a in self.config_data["accounts"] if _account_key(a) == key), None
        )

        if password:
            secrets.set(key, password)
        if existing is None:
            self.config_data["accounts"].append({"user": user, "server": server})
            save_config(self.config_data)

        self.user.delete(0, tk.END)
        self.server.delete(0, tk.END)
        self.password.delete(0, tk.END)
        self.auto_register_accounts()

    def auto_register_accounts(self):
        for entry in self.accounts:
            try:
                entry["acc"].delete()
            except Exception:
                pass
        self.accounts = []

        for data in self.config_data["accounts"]:
            try:
                self.register_account(data)
            except Exception as e:
                logging.error("Erro ao registrar %s@%s: %s", data["user"], data["server"], e)
        self.refresh()
        self.update_presence()

    def register_account(self, data):
        user = data["user"]
        server = data["server"]

        acfg = pj.AccountConfig()
        acfg.idUri = f"sip:{user}@{server}"
        acfg.regConfig.registrarUri = f"sip:{server}"

        password = secrets.get(f"{user}@{server}", "")
        cred = pj.AuthCredInfo("digest", "*", user, 0, password)
        acfg.sipConfig.authCreds.append(cred)

        acc = MyAccount(self, data)
        acc.create(acfg)
        if not self.accounts:
            acc.setDefault()

        self.accounts.append({"acc": acc, "data": dict(data), "status": "REGISTERING"})

    def edit_account(self):
        if self.call_state != "IDLE":
            messagebox.showwarning(
                "Chamada em andamento",
                "Encerre a chamada atual antes de editar uma conta.",
            )
            return
        entry = self.selected_account()
        if entry is None:
            messagebox.showinfo("Nenhuma seleção", "Selecione uma conta na lista.")
            return

        if self.edit_win is not None:
            try:
                self.edit_win.destroy()
            except tk.TclError:
                pass
            self.edit_win = None

        win = tk.Toplevel(self.root)
        win.title("Editar conta")
        win.geometry("380x250")
        win.minsize(340, 220)
        win.transient(self.root)
        self._edit_entry = entry
        win.protocol(
            "WM_DELETE_WINDOW",
            lambda: (
                win.destroy(),
                setattr(self, "edit_win", None),
                setattr(self, "_edit_entry", None),
            ),
        )
        self.edit_win = win

        try:
            old_user = entry["data"]["user"]
            old_server = entry["data"]["server"]

            container = ttk.Frame(win, padding=10)
            container.pack(fill=tk.BOTH, expand=True)
            container.grid_columnconfigure(1, weight=1)

            ttk.Label(container, text="Servidor").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
            self.edit_server = ttk.Entry(container)
            self.edit_server.insert(0, old_server)
            self.edit_server.grid(row=0, column=1, sticky="ew", pady=3)
            ToolTip(self.edit_server, "Endereço do servidor SIP (ex.: 10.0.0.1 ou pbx.empresa.com.br)")

            ttk.Label(container, text="Ramal").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
            self.edit_user = ttk.Entry(container)
            self.edit_user.insert(0, old_user)
            self.edit_user.grid(row=1, column=1, sticky="ew", pady=3)
            ToolTip(self.edit_user, "Número do seu ramal")

            ttk.Label(container, text="Senha").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=3)
            self.edit_password = ttk.Entry(container, show="*")
            self.edit_password.grid(row=2, column=1, sticky="ew", pady=3)
            ToolTip(self.edit_password, "Nova senha (vazio = manter a atual)")

            self._styled_button(
                container, "💾  Salvar alterações", self.save_edit_account, COLOR_SUCCESS
            ).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 4))

            self._styled_button(container, "Fechar", win.destroy, COLOR_PRIMARY).grid(
                row=4, column=0, columnspan=2, sticky="ew"
            )

            self.root.update_idletasks()
            win.grab_set()
        except Exception as e:
            logging.exception("Erro ao abrir a janela de edição de conta")
            try:
                win.destroy()
            except tk.TclError:
                pass
            self.edit_win = None
            self._edit_entry = None
            messagebox.showerror(
                "Erro",
                f"Não foi possível abrir a janela de edição:\n{e}",
            )

    def save_edit_account(self):
        if self.edit_win is None:
            return
        entry = self._edit_entry if self._edit_entry is not None else self.selected_account()
        if entry is None or entry not in self.accounts:
            messagebox.showerror("Erro", "Conta não encontrada na lista.")
            return

        old_user = entry["data"]["user"]
        old_server = entry["data"]["server"]
        old_key = f"{old_user}@{old_server}"

        user = clean_extension(self.edit_user.get())
        server = self.edit_server.get().strip()
        password = self.edit_password.get()

        if not is_valid_extension(user):
            messagebox.showerror("Erro", "Ramal inválido (use apenas letras, números, _ . + -).")
            return
        if not is_valid_server(server):
            messagebox.showerror("Erro", "Servidor inválido.")
            return

        new_key = f"{user}@{server}"
        if new_key != old_key:
            other = next(
                (a for a in self.config_data["accounts"] if _account_key(a) == new_key), None
            )
            if other is not None:
                messagebox.showerror("Erro", f"Já existe uma conta com o ramal {user}@{server}.")
                return

        if password:
            secrets.set(new_key, password)
        elif new_key != old_key:
            old_password = secrets.get(old_key, "")
            if old_password:
                secrets.set(new_key, old_password)

        if new_key != old_key:
            secrets.delete(old_key)

        for i, acc_cfg in enumerate(self.config_data["accounts"]):
            if _account_key(acc_cfg) == old_key:
                self.config_data["accounts"][i] = {"user": user, "server": server}
                break

        save_config(self.config_data)

        try:
            entry["acc"].delete()
        except Exception as e:
            logging.warning("Erro ao remover conta antiga do pjsip: %s", e)
        self.accounts.remove(entry)

        self.edit_win.destroy()
        self.edit_win = None
        self._edit_entry = None
        self.auto_register_accounts()

    def delete_account(self):
        if self.call_state != "IDLE":
            messagebox.showwarning(
                "Chamada em andamento",
                "Encerre a chamada atual antes de deletar uma conta.",
            )
            return
        entry = self.selected_account()
        if entry is None:
            messagebox.showinfo("Nenhuma seleção", "Selecione uma conta na lista.")
            return

        user, server = entry["data"]["user"], entry["data"]["server"]
        try:
            entry["acc"].delete()
        except Exception as e:
            logging.warning("Erro ao remover conta do pjsip: %s", e)

        self.accounts.remove(entry)
        self.config_data["accounts"] = [
            a for a in self.config_data["accounts"]
            if not (a["user"] == user and a["server"] == server)
        ]
        secrets.delete(f"{user}@{server}")
        save_config(self.config_data)
        self.refresh()
        self.update_presence()

    def selected_account(self):
        sel = self.listbox.curselection()
        if sel:
            idx = sel[0]
            if idx < len(self.accounts):
                return self.accounts[idx]
        return None

    def update_account_status(self, acc, status):
        for entry in self.accounts:
            if entry["acc"] == acc:
                entry["status"] = status
                break
        self.refresh()
        self.update_presence()

    def refresh(self):
        keep = self.listbox.curselection()
        keep_idx = keep[0] if keep else None

        self.listbox.delete(0, tk.END)
        status_cfg = {
            "ONLINE": (COLOR_SUCCESS, "●", "ONLINE"),
            "REGISTERING": (COLOR_WARNING, "◐", "REGISTRANDO"),
            "OFFLINE": (COLOR_DANGER, "○", "OFFLINE"),
        }
        for i, entry in enumerate(self.accounts):
            status = entry["status"]
            color, icon, label = status_cfg.get(status, (COLOR_MUTED, "○", status))
            self.listbox.insert(
                tk.END,
                f"{icon}  {entry['data']['user']}@{entry['data']['server']}  ({label})",
            )
            try:
                self.listbox.itemconfig(
                    i,
                    fg=color,
                    bg=COLOR_LIST_EVEN if i % 2 == 0 else COLOR_LIST_ODD,
                    selectbackground=COLOR_PRIMARY,
                    selectforeground="#FFFFFF",
                )
            except tk.TclError:
                pass

        if keep_idx is not None and keep_idx < self.listbox.size():
            self.listbox.selection_set(keep_idx)

    # =========================
    # CHAMADAS
    # =========================
    def record_call(self, label):
        self.history.append(
            {"ts": datetime.now().strftime("%d/%m/%Y %H:%M"), "label": label}
        )
        if len(self.history) > 500:
            self.history = self.history[-500:]
        save_history(self.history)

    def show_history(self):
        win = tk.Toplevel(self.root)
        win.title("Histórico de Chamadas")
        win.geometry("540x420")
        win.minsize(480, 320)
        win.transient(self.root)
        win.grab_set()
        self.history_win = win
        win.protocol("WM_DELETE_WINDOW", lambda: (win.destroy(), setattr(self, "history_win", None)))

        container = ttk.Frame(win, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        columns = ("data", "tipo", "numero")
        tree = ttk.Treeview(container, columns=columns, show="headings", selectmode="browse")
        tree.heading("data", text="Data/Hora")
        tree.heading("tipo", text="Tipo")
        tree.heading("numero", text="Número/Contato")
        tree.column("data", width=140, anchor="w")
        tree.column("tipo", width=80, anchor="center")
        tree.column("numero", width=280, anchor="w")
        tree.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        for entry in reversed(self.history):
            tipo, numero = self._split_history_label(entry["label"])
            tree.insert("", tk.END, values=(entry["ts"], tipo, numero))

        btn_frame = tk.Frame(container, bg=COLOR_BG)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        btn_frame.grid_columnconfigure(0, weight=1)
        self._styled_button(
            btn_frame, "🗑  Limpar", lambda: self._clear_history_ui(tree, win), COLOR_DANGER
        ).grid(row=0, column=0, sticky="w")
        self._styled_button(btn_frame, "Fechar", win.destroy, COLOR_PRIMARY).grid(
            row=0, column=1, sticky="e"
        )

    @staticmethod
    def _split_history_label(label):
        for prefix, tipo in (("Saída para ", "Saída"), ("Entrada de ", "Entrada")):
            if label.startswith(prefix):
                return tipo, label[len(prefix):]
        return "—", label

    def _clear_history_ui(self, tree, win):
        if not self.history:
            return
        if not messagebox.askyesno("Limpar Histórico", "Apagar todo o histórico de chamadas?"):
            return
        self.history = []
        save_history(self.history)
        for item in tree.get_children():
            tree.delete(item)
        win.destroy()

    def clear_history(self):
        if not self.history:
            return
        if not messagebox.askyesno("Limpar Histórico", "Apagar todo o histórico de chamadas?"):
            return
        self.history = []
        save_history(self.history)

    def make_call(self):
        entry = self.selected_account()
        if entry is None:
            for a in self.accounts:
                if a["status"] == "ONLINE":
                    entry = a
                    break
        if entry is None and self.accounts:
            entry = self.accounts[0]
        if entry is None:
            messagebox.showwarning("Sem contas", "Adicione e registre uma conta primeiro.")
            return

        number = clean_extension(self.number.get())
        if not number:
            messagebox.showwarning("Número inválido", "Informe um número para ligar.")
            return

        dest = f"sip:{number}@{entry['data']['server']}"
        logging.info("Ligando para %s usando a conta %s", dest, entry["data"]["user"])

        try:
            if self.current_call is not None and self.current_call is not self.incoming_call:
                self._disconnect_call_media()
                if self._call_is_confirmed(self.current_call):
                    self._hold_call(self.current_call)

            self.muted = False
            self.current_call = MyCall(entry["acc"], self)
            self.current_call.makeCall(dest, pj.CallOpParam(True))
            self._track_call(self.current_call)
            self.held_calls.discard(self.current_call.getId())
            self.set_call_state("CALLING")
            self._start_ringback()
            self.record_call(f"Saída para {number}")
            self.update_call_ui()
        except Exception as e:
            logging.error("Erro ao ligar: %s", e)
            messagebox.showerror("Erro", f"Falha ao ligar: {e}")

    def on_incoming(self, call):
        self._track_call(call)
        if self.current_call is not None and self.call_state in ("IN_CALL", "HOLD"):
            prev = self.current_call
            self._disconnect_call_media()
            if self._call_is_confirmed(prev):
                self._hold_call(prev)
        self.current_call = call
        self.incoming_call = call
        self.muted = False
        self.set_call_state("INCOMING")
        try:
            remote = call.getInfo().remoteUri
        except Exception as e:
            logging.warning("Falha ao obter URI da chamada de entrada: %s", e)
            remote = "desconhecido"
        self.record_call(f"Entrada de {remote}")
        self.update_call_ui()

    def answer(self):
        if self.current_call is None:
            return
        try:
            op = pj.CallOpParam()
            op.statusCode = 200
            self.current_call.answer(op)
            self.incoming_call = None
            self.set_call_state("CALLING")
            self.update_call_ui()
        except Exception as e:
            logging.error("Erro ao atender: %s", e)
            messagebox.showerror("Erro", f"Falha ao atender: {e}")

    def hangup(self):
        call = self.current_call
        self.current_call = None
        self.incoming_call = None
        self.current_audio_media = None
        self.muted = False
        self.btn_mute.config(text="Mute")

        if call is not None:
            try:
                call.hangup(pj.CallOpParam())
            except Exception as e:
                logging.error("Erro ao desligar: %s", e)

        self._stop_ringback()
        self.set_call_state("IDLE")
        self.update_call_ui()
    def handle_call_state(self, call, prm):
        try:
            ci = call.getInfo()
        except Exception as e:
            logging.warning("Sessão de chamada já encerrada (getInfo falhou): %s", e)
            self.on_call_disconnected(call)
            return
        logging.info("Chamada %s: estado %s", ci.id, ci.stateText)

        if ci.state in (
            pj.PJSIP_INV_STATE_CALLING,
            pj.PJSIP_INV_STATE_EARLY,
            pj.PJSIP_INV_STATE_CONFIRMED,
        ):
            self._track_call(call)

        if ci.state == pj.PJSIP_INV_STATE_CALLING:
            if call is self.current_call:
                self.set_call_state("CALLING")
        elif ci.state == pj.PJSIP_INV_STATE_INCOMING:
            if call is self.current_call:
                self.set_call_state("INCOMING")
        elif ci.state == pj.PJSIP_INV_STATE_EARLY:
            if call is self.current_call:
                self.set_call_state("RINGING")
        elif ci.state == pj.PJSIP_INV_STATE_CONFIRMED:
            self._stop_ringback()
            if self._pending_xfer is not None and self._pending_xfer.get("dst") is call:
                self._complete_attended_xfer(call)
            if call is self.current_call:
                self._connect_call_media(call)
                self.set_call_state("IN_CALL")
        elif ci.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            self.on_call_disconnected(call)
        self.update_call_ui()

    def on_call_disconnected(self, call):
        self._after_call_ended(call)
        self.update_call_ui()

    # =========================
    # MÚLTIPLAS CHAMADAS / ESPERA / TRANSFERÊNCIA
    # =========================
    def _track_call(self, call):
        try:
            cid = call.getId()
        except Exception:
            return
        if cid >= 0:
            self.calls[cid] = call

    def _forget_call(self, call):
        try:
            cid = call.getId()
        except Exception:
            return
        self.calls.pop(cid, None)
        self.held_calls.discard(cid)

    def _call_is_confirmed(self, call):
        try:
            return call.getInfo().state == pj.PJSIP_INV_STATE_CONFIRMED
        except Exception:
            return False

    def _call_label(self, call):
        try:
            remote = call.getInfo().remoteUri
        except Exception:
            return "Chamada"
        if remote.startswith("sip:"):
            remote = remote[4:]
        if "@" in remote:
            remote = remote.split("@", 1)[0]
        return remote

    def _call_server(self, call):
        acc = getattr(call, "acc", None)
        if acc is not None:
            return acc.data.get("server", "")
        return ""

    def _hold_call(self, call):
        try:
            cid = call.getId()
        except Exception:
            return
        if cid in self.held_calls or not self._call_is_confirmed(call):
            return
        try:
            op = pj.CallOpParam()
            call.setHold(op)
            self.held_calls.add(cid)
            logging.info("Chamada %s colocada em espera", cid)
        except Exception as e:
            logging.error("Erro ao colocar chamada em espera: %s", e)

    def _unhold_call(self, call):
        try:
            cid = call.getId()
        except Exception:
            return
        if cid not in self.held_calls:
            return
        try:
            op = pj.CallOpParam()
            op.opt.audioCount = 1
            op.opt.videoCount = 0
            op.opt.flag = pj.PJSUA_CALL_UNHOLD | pj.PJSUA_CALL_UPDATE_CONTACT
            call.reinvite(op)
            self.held_calls.discard(cid)
            logging.info("Chamada %s retomada", cid)
        except Exception as e:
            logging.error("Erro ao retomar chamada: %s", e)

    def _disconnect_call_media(self):
        if self.current_audio_media is None:
            return
        try:
            mic = self.endpoint.audDevManager().getCaptureDevMedia()
            spk = self.endpoint.audDevManager().getPlaybackDevMedia()
            mic.stopTransmit(self.current_audio_media)
            self.current_audio_media.stopTransmit(spk)
        except Exception as e:
            logging.error("Erro ao desconectar áudio: %s", e)
        finally:
            self.current_audio_media = None

    def _pick_other_call(self, exclude=None):
        for cid in sorted(self.calls):
            call = self.calls[cid]
            if call is exclude:
                continue
            if self._call_is_confirmed(call):
                return call
        for cid in sorted(self.calls):
            call = self.calls[cid]
            if call is exclude:
                continue
            return call
        return None

    def _activate_call(self, call):
        if call is None:
            return
        prev = self.current_call
        if prev is not None and prev is not call:
            self._disconnect_call_media()
            if self._call_is_confirmed(prev):
                self._hold_call(prev)
        self.current_call = call
        self.incoming_call = None
        self.muted = False
        try:
            state = call.getInfo().state
        except Exception:
            return
        if state == pj.PJSIP_INV_STATE_CONFIRMED:
            if call.getId() in self.held_calls:
                self._unhold_call(call)
            self._connect_call_media(call)
            self.set_call_state("IN_CALL")
        elif state == pj.PJSIP_INV_STATE_INCOMING:
            self.set_call_state("INCOMING")
        elif state == pj.PJSIP_INV_STATE_CALLING:
            self._start_ringback()
            self.set_call_state("CALLING")
        elif state == pj.PJSIP_INV_STATE_EARLY:
            self.set_call_state("RINGING")
        self.update_call_ui()

    def _after_call_ended(self, call):
        self._forget_call(call)
        self._stop_ringback()
        nxt = self._pick_other_call(exclude=call)
        if nxt is not None:
            self._activate_call(nxt)
        else:
            self.current_call = None
            self.incoming_call = None
            self.current_audio_media = None
            self.muted = False
            self.btn_mute.config(text="Mute")
            self.set_call_state("IDLE")

    def toggle_hold(self):
        call = self.current_call
        if call is None or self.call_state not in ("IN_CALL", "HOLD"):
            return
        if call.getId() in self.held_calls:
            self._unhold_call(call)
            self._connect_call_media(call)
            self.set_call_state("IN_CALL")
        else:
            self._disconnect_call_media()
            self._hold_call(call)
            self.set_call_state("HOLD")
        self.update_call_ui()

    def refresh_call_switcher(self):
        if not hasattr(self, "call_switch_box"):
            return
        self._switch_call_ids = []
        labels = []
        for cid in sorted(self.calls):
            call = self.calls[cid]
            try:
                call.getInfo()
            except Exception:
                continue
            label = self._call_label(call)
            if cid in self.held_calls:
                status = "Em espera"
            elif call is self.current_call:
                status = "Ativa"
            else:
                status = "Secundária"
            labels.append(f"{label} ({status})")
            self._switch_call_ids.append(cid)
        self.call_switch_box["values"] = labels
        try:
            if self.current_call is not None:
                cur_id = self.current_call.getId()
                if cur_id in self._switch_call_ids:
                    self.call_switch_box.current(self._switch_call_ids.index(cur_id))
                else:
                    self.call_switch_box.current(-1)
            else:
                self.call_switch_box.current(-1)
        except Exception:
            pass

    def alternate_call(self):
        idx = self.call_switch_box.current()
        if idx < 0 or idx >= len(self._switch_call_ids):
            return
        call = self.calls.get(self._switch_call_ids[idx])
        if call is None:
            return
        if call is self.current_call:
            if call.getId() in self.held_calls:
                self._unhold_call(call)
                self._connect_call_media(call)
                self.set_call_state("IN_CALL")
                self.update_call_ui()
            return
        self._activate_call(call)
        self.refresh_call_switcher()

    def open_transfer(self):
        call = self.current_call
        if call is None:
            return
        if self.transfer_win is not None:
            try:
                self.transfer_win.deiconify()
                self.transfer_win.lift()
                return
            except Exception:
                self.transfer_win = None
        win = tk.Toplevel(self.root)
        self.transfer_win = win
        win.title("Transferir chamada")
        win.geometry("380x180")
        win.configure(bg=COLOR_CARD)
        win.transient(self.root)
        ttk.Label(win, text="Ramal/número de destino:").pack(
            padx=12, pady=(14, 4), anchor="w"
        )
        entry = ttk.Entry(win)
        entry.pack(fill="x", padx=12, pady=4)
        entry.focus_set()
        btns = tk.Frame(win, bg=COLOR_CARD)
        btns.pack(fill="x", padx=12, pady=(12, 12))
        btns.grid_columnconfigure(0, weight=1)
        btns.grid_columnconfigure(1, weight=1)
        self._styled_button(
            btns, "Cega", lambda: self._blind_transfer(entry.get()), COLOR_PRIMARY
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._styled_button(
            btns, "Assistida", lambda: self._attended_transfer(entry.get()), COLOR_SUCCESS
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        entry.bind("<Return>", lambda e: self._blind_transfer(entry.get()))
        win.protocol("WM_DELETE_WINDOW", self._close_transfer_win)

    def _close_transfer_win(self):
        if self.transfer_win is not None:
            try:
                self.transfer_win.destroy()
            except Exception:
                pass
            self.transfer_win = None

    def _blind_transfer(self, raw):
        num = clean_extension(raw)
        call = self.current_call
        if not num or call is None:
            return
        try:
            server = self._call_server(call)
            op = pj.CallOpParam()
            call.xfer(f"sip:{num}@{server}", op)
            self.record_call(f"Transferência cega para {num}")
            logging.info("Transferência cega para %s", num)
            self._close_transfer_win()
        except Exception as e:
            logging.error("Erro na transferência cega: %s", e)
            messagebox.showerror("Transferir", f"Falha na transferência: {e}")

    def _attended_transfer(self, raw):
        num = clean_extension(raw)
        call = self.current_call
        if not num or call is None:
            return
        acc = getattr(call, "acc", None)
        if acc is None:
            return
        try:
            server = self._call_server(call)
            op = pj.CallOpParam(True)
            call2 = MyCall(acc, self)
            call2.makeCall(f"sip:{num}@{server}", op)
            self._pending_xfer = {"src": call, "dst": call2, "num": num}
            self._track_call(call2)
            if call.getId() not in self.held_calls:
                self._hold_call(call)
            self.current_call = call2
            self.incoming_call = None
            self.set_call_state("CALLING")
            self._start_ringback()
            self.record_call(f"Transferência assistida para {num}")
            logging.info("Transferência assistida para %s", num)
            self._close_transfer_win()
            self.update_call_ui()
        except Exception as e:
            logging.error("Erro na transferência assistida: %s", e)
            messagebox.showerror("Transferir", f"Falha ao iniciar a transferência: {e}")

    def _complete_attended_xfer(self, dst_call):
        px = self._pending_xfer
        if not px or px.get("dst") is not dst_call:
            return
        src = px.get("src")
        self._pending_xfer = None
        if src is None:
            return
        try:
            op = pj.CallOpParam()
            src.xferReplaces(dst_call, op)
            self.record_call(f"Transferência assistida concluída para {px.get('num', '')}")
            logging.info("Transferência assistida concluída")
        except Exception as e:
            logging.error("Erro ao completar transferência: %s", e)
            messagebox.showerror("Transferir", f"Falha ao concluir a transferência: {e}")

    def pickup_call(self):
        code = self.pickup_code
        self.number.delete(0, tk.END)
        self.number.insert(0, code)
        self.make_call()

    def _connect_call_media(self, call):
        try:
            ci = call.getInfo()
        except Exception as e:
            logging.warning("Sessão de chamada já encerrada no media state: %s", e)
            return
        try:
            for mi in ci.media:
                if (
                    mi.type == pj.PJMEDIA_TYPE_AUDIO
                    and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE
                ):
                    med = call.getMedia(mi.index)
                    audio = pj.AudioMedia.typecastFromMedia(med)

                    mic = self.endpoint.audDevManager().getCaptureDevMedia()
                    spk = self.endpoint.audDevManager().getPlaybackDevMedia()

                    if not self.muted:
                        mic.startTransmit(audio)
                    audio.startTransmit(spk)

                    self.current_audio_media = audio
                    self.apply_volumes()
                    return
        except Exception as e:
            logging.error("Erro de áudio na chamada: %s", e)

    def on_call_media_state(self, call):
        if call is self.current_call:
            self._connect_call_media(call)
            if self.current_audio_media is not None and not self._call_is_confirmed(call):
                self._stop_ringback()
                logging.info("Mídia antecipada ativa durante o chamado (early media); ringback parado")
        self.update_call_ui()

    def set_call_state(self, state):
        self.call_state = state
        if state == "IDLE":
            self.update_presence()
        else:
            label = STATE_LABELS.get(state, state)
            self.status_label.config(text=f"Status: {label}")
            self.status_canvas.itemconfig(self.status_dot, fill=STATUS_COLORS.get(state, COLOR_MUTED))
        if state == "INCOMING":
            self._blink_answer(True)
            self._start_ringtone()
            self._notify_incoming()
        else:
            self._blink_answer(False)
            self._stop_ringtone()
            if self.root.title() != self._base_title:
                self.root.title(self._base_title)

    def update_presence(self):
        """Reflete o registro SIP no indicador quando ocioso:
        Disponível (verde) somente se houver conta logada; caso contrário, Offline (cinza)."""
        if self.call_state != "IDLE":
            return
        if any(entry["status"] == "ONLINE" for entry in self.accounts):
            self.status_label.config(text=f"Status: {STATE_LABELS['IDLE']}")
            self.status_canvas.itemconfig(self.status_dot, fill=STATUS_COLORS["IDLE"])
        else:
            self.status_label.config(text="Status: Offline")
            self.status_canvas.itemconfig(self.status_dot, fill=COLOR_OFFLINE)

    def _notify_incoming(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.root.attributes("-topmost", True)
            self.root.after(3000, lambda: self.root.attributes("-topmost", False))
            self.root.title(f"Chamada recebida! - {self._base_title}")
            self.root.bell()
        except Exception as e:
            logging.warning("Falha ao notificar chamada recebida: %s", e)

    def _ringtone_path(self):
        path = (self.config_data.get("ringtone") or "").strip()
        if path and os.path.isfile(path):
            return path
        default = resource_path(RINGTONE_FILE)
        return default if os.path.isfile(default) else None

    def _ringtone_display(self):
        path = (self.config_data.get("ringtone") or "").strip()
        if path and os.path.isfile(path):
            return os.path.basename(path)
        return "(padrão)"

    def _pick_ringtone(self):
        path = filedialog.askopenfilename(
            parent=self.settings_win,
            title="Escolher toque de chamada (WAV)",
            filetypes=[("Áudio WAV", "*.wav"), ("Todos os arquivos", "*.*")],
        )
        if not path:
            return
        self.config_data["ringtone"] = path
        save_config(self.config_data)
        self.ringtone_var.set(os.path.basename(path))
        logging.info("Toque de chamada definido: %s", path)

    def _reset_ringtone(self):
        self.config_data["ringtone"] = ""
        save_config(self.config_data)
        self.ringtone_var.set("(padrão)")
        logging.info("Toque de chamada restaurado para o padrão")

    def _stop_test_player(self):
        if self._test_stop_job is not None:
            try:
                self.root.after_cancel(self._test_stop_job)
            except Exception:
                pass
            self._test_stop_job = None
        if self._test_player is None:
            return
        try:
            spk = self.endpoint.audDevManager().getPlaybackDevMedia()
            self._test_player.stopTransmit(spk)
        except Exception:
            pass
        self._test_player = None

    def _test_ringtone(self):
        path = self._ringtone_path()
        if not path:
            messagebox.showinfo("Toque", "Nenhum arquivo de toque disponível.")
            return
        self._stop_test_player()
        try:
            player = pj.AudioMediaPlayer()
            player.createPlayer(path, pj.PJMEDIA_FILE_NO_LOOP)
            spk = self.endpoint.audDevManager().getPlaybackDevMedia()
            player.startTransmit(spk)
            self._test_player = player
            self._test_stop_job = self.root.after(9000, self._stop_test_player)
            logging.info("Testando toque de chamada: %s", path)
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível tocar o arquivo: {e}")
            logging.error("Erro ao testar toque de chamada: %s", e)

    def _play_tone(self, freq, on_msec, off_msec):
        """Cria um tom em loop e o transmite ao dispositivo de saída."""
        tg = pj.ToneGenerator()
        tg.createToneGenerator(8000)
        desc = pj.ToneDesc()
        desc.freq1 = freq
        desc.freq2 = 0
        desc.on_msec = on_msec
        desc.off_msec = off_msec
        desc.volume = 0  # 0 = volume padrão (PJMEDIA_TONEGEN_VOLUME)
        vec = pj.ToneDescVector()
        vec.push_back(desc)
        tg.play(vec, True)
        spk = self.endpoint.audDevManager().getPlaybackDevMedia()
        tg.startTransmit(spk)
        return tg

    def _start_ringtone(self):
        if self._ringtone is not None or self._ringtone_player is not None:
            return
        path = self._ringtone_path()
        if path:
            try:
                player = pj.AudioMediaPlayer()
                player.createPlayer(path, 0)  # 0 = loop
                spk = self.endpoint.audDevManager().getPlaybackDevMedia()
                player.startTransmit(spk)
                self._ringtone_player = player
                logging.info("Tocando toque de chamada recebida: %s", path)
                return
            except Exception as e:
                logging.error("Falha ao tocar arquivo de toque (%s); usando tom padrão", e)
                self._ringtone_player = None
        try:
            self._ringtone = self._play_tone(440, 2000, 3000)
            logging.info("Tocando tom de chamada recebida")
        except Exception as e:
            self._ringtone = None
            logging.error("Erro ao tocar tom de chamada recebida: %s", e)

    def _stop_ringtone(self):
        stopped = False
        if self._ringtone_player is not None:
            try:
                spk = self.endpoint.audDevManager().getPlaybackDevMedia()
                self._ringtone_player.stopTransmit(spk)
                self._ringtone_player = None
                stopped = True
            except Exception as e:
                logging.error("Erro ao parar toque de chamada: %s", e)
                self._ringtone_player = None
        if self._ringtone is not None:
            try:
                spk = self.endpoint.audDevManager().getPlaybackDevMedia()
                self._ringtone.stopTransmit(spk)
                self._ringtone.stop()
            except Exception as e:
                logging.error("Erro ao parar tom de chamada recebida: %s", e)
            finally:
                self._ringtone = None
            stopped = True
        if stopped:
            logging.info("Toque de chamada recebida parado")

    def _start_ringback(self):
        if self._ringback is not None:
            return
        try:
            self._ringback = self._play_tone(425, 1000, 4000)
        except Exception as e:
            self._ringback = None
            logging.error("Erro ao tocar ringback: %s", e)

    def _stop_ringback(self):
        if self._ringback is None:
            return
        try:
            spk = self.endpoint.audDevManager().getPlaybackDevMedia()
            self._ringback.stopTransmit(spk)
            self._ringback.stop()
        except Exception as e:
            logging.error("Erro ao parar ringback: %s", e)
        finally:
            self._ringback = None

    def update_call_ui(self):
        busy = self.call_state in ("CALLING", "RINGING", "INCOMING", "IN_CALL", "HOLD")
        self.btn_call.config(state=tk.NORMAL if not busy else tk.DISABLED)
        self.btn_answer.config(
            state=tk.NORMAL if self.call_state == "INCOMING" else tk.DISABLED
        )
        self.btn_hangup.config(state=tk.NORMAL if self.current_call is not None else tk.DISABLED)
        self.btn_mute.config(
            state=tk.NORMAL if self.current_audio_media is not None else tk.DISABLED
        )
        if hasattr(self, "btn_hold"):
            self.btn_hold.config(
                state=tk.NORMAL
                if self.current_call is not None and self.call_state in ("IN_CALL", "HOLD")
                else tk.DISABLED
            )
        if hasattr(self, "btn_transfer"):
            self.btn_transfer.config(
                state=tk.NORMAL
                if self.current_call is not None and self.call_state in ("IN_CALL", "HOLD")
                else tk.DISABLED
            )
        if hasattr(self, "btn_pickup"):
            self.btn_pickup.config(state=tk.NORMAL)
        self.refresh_call_switcher()

    def _blink_answer(self, active=None):
        if active is None:
            active = self.call_state == "INCOMING"
        if active:
            if not self._answer_blink_on:
                self._answer_blink_on = True
                self._answer_blink_job = self.root.after(0, self._answer_blink_tick)
        else:
            self._answer_blink_on = False
            self._answer_blink_job = None
            if hasattr(self, "btn_answer"):
                self.btn_answer.config(bg=COLOR_PRIMARY)

    def _answer_blink_tick(self):
        if not getattr(self, "_answer_blink_on", False):
            return
        current = self.btn_answer.cget("bg")
        target = COLOR_WARNING if current == COLOR_PRIMARY else COLOR_PRIMARY
        self.btn_answer.config(bg=target)
        self._answer_blink_job = self.root.after(500, self._answer_blink_tick)

    # =========================
    # ÁUDIO
    # =========================
    def apply_volumes(self):
        if self.current_audio_media is None:
            return
        try:
            self.current_audio_media.adjustRxLevel(self.volume_out / 5.0)
            self.current_audio_media.adjustTxLevel(self.volume_in / 5.0)
        except Exception as e:
            logging.error("Erro ao ajustar volume: %s", e)

    def on_volume_out(self, value):
        self.volume_out = float(value)
        self.apply_volumes()

    def on_volume_in(self, value):
        self.volume_in = float(value)
        self.apply_volumes()

    def toggle_mute(self):
        if self.current_audio_media is None:
            return
        mic = self.endpoint.audDevManager().getCaptureDevMedia()
        try:
            if self.muted:
                mic.startTransmit(self.current_audio_media)
                self.muted = False
                self.btn_mute.config(text="Mute")
            else:
                mic.stopTransmit(self.current_audio_media)
                self.muted = True
                self.btn_mute.config(text="Unmute")
        except Exception as e:
            logging.error("Erro no mute: %s", e)

    # =========================
    # DISPOSITIVOS
    # =========================
    def load_devices(self):
        try:
            devs = self.endpoint.audDevManager().enumDev2()
        except Exception as e:
            logging.error("Erro ao listar dispositivos: %s", e)
            return

        ins, outs = [], []
        for index, d in enumerate(devs):
            if d.inputCount:
                ins.append((index, d.name))
            if d.outputCount:
                outs.append((index, d.name))

        if self.settings_win is not None:
            self.input_devices["values"] = [f"{i} | {n}" for i, n in ins]
            self.output_devices["values"] = [f"{i} | {n}" for i, n in outs]

    def apply_devices(self):
        if self.settings_win is None:
            messagebox.showinfo("Configurações", "Abra Configurações > Áudio para escolher dispositivos.")
            return
        try:
            adm = self.endpoint.audDevManager()
            sel = self.input_devices.get()
            if sel:
                adm.setCaptureDev(int(sel.split(" | ")[0]))
            sel = self.output_devices.get()
            if sel:
                adm.setPlaybackDev(int(sel.split(" | ")[0]))
            logging.info("Dispositivos aplicados: entrada=%s saída=%s",
                         self.input_devices.get(), self.output_devices.get())
        except Exception as e:
            logging.error("Erro ao aplicar dispositivos: %s", e)
            messagebox.showerror("Erro", f"Falha ao aplicar dispositivos: {e}")

    # =========================
    # LOOP / ENCERRAMENTO
    # =========================
    def _ui(self, fn, *args):
        """Executa fn na thread principal do Tk (callbacks do pjsua são de outra thread)."""
        if threading.get_ident() == self._main_tid:
            fn(*args)
        else:
            self._ui_queue.put((fn, args))

    def loop(self):
        try:
            while True:
                fn, args = self._ui_queue.get_nowait()
                try:
                    fn(*args)
                except Exception as e:
                    logging.error("Erro em callback de UI: %s", e)
        except queue.Empty:
            pass
        try:
            if self.endpoint:
                self.endpoint.libHandleEvents(50)
        except Exception as e:
            logging.error("Erro no loop pjsip: %s", e)
        self.root.after(50, self.loop)

    def close(self):
        try:
            self._answer_blink_on = False
            if getattr(self, "_answer_blink_job", None):
                try:
                    self.root.after_cancel(self._answer_blink_job)
                except Exception:
                    pass
            self._close_transfer_win()
            self._stop_ringback()
            self._stop_ringtone()
            self._stop_test_player()
            self.calls.clear()
            for entry in self.accounts:
                try:
                    entry["acc"].delete()
                except Exception:
                    pass
            if self.endpoint:
                self.endpoint.libDestroy()
        except Exception as e:
            logging.error("Erro ao encerrar: %s", e)
        self.root.destroy()


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    setup_logging()
    secrets = SecretsStore()
    root = tk.Tk(className="Voiceneves")
    app = SoftphoneApp(root)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()
