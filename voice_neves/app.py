"""Interface grafica (tkinter) + controlador do softphone (pjsua2).

Este modulo concentra toda a UI e o estado do SoftphoneApp, mantendo as
globais mutaveis de cor (COLOR_*) no mesmo namespace -- exatamente como no
softphone.py original -- para que set_theme() continue funcionando. Toda a
logica pura (config, historico, contatos, secrets, ldap, modelos pjsip) vive
em modulos separados do pacote voice_neves.
"""
import os
import sys
import csv
import json
import re
import time
import logging
import threading
import queue
import subprocess
import webbrowser
from datetime import datetime

import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog, ttk, font as tkfont

# pjsua2 é o binding SIP (Linux no build atual). Em Win/Mac fica None -- a UI
# abre e o app sinaliza "Backend SIP indisponível". Veja sip_backend.py.
from . import sip_backend
from . import platform
pj = sip_backend.import_pjsua2()

try:
    import pystray
    from PIL import Image as PILImage
    HAVE_TRAY = True
except Exception:
    pystray = None
    PILImage = None
    HAVE_TRAY = False

try:
    from pynput import keyboard as pynput_keyboard
    HAVE_HOTKEYS = True
except Exception:
    pynput_keyboard = None
    HAVE_HOTKEYS = False

from .constants import *  # noqa: F401,F403  (APP_*, paths, regex, codecs, STATE_LABELS, COLOR_OFFLINE)
from .constants import CONFIG_DIR, DATA_DIR  # explicitas (usadas por tooling)
from .themes import THEMES
from .platform import detect_system_theme
from .runtime import secrets
from .utils import (
    resource_path, notify_send, is_wayland, appindicator_available,
    clean_extension, is_valid_extension, is_valid_server,
    build_sip_target, _as_bool,
)
from .config import _account_key, _clean_ldap, _clean_zrtp, load_config, save_config
from .history import load_history, save_history
from .contacts_store import ContactsStore
from .ldap_manager import LDAPManager
from .pjsip_models import MyAccount, MyBuddy, MyCall



def pj_error_text(e):
    """Formata um erro do pjsua2 (pj.Error) com a mensagem real do PJSIP.

    O str() de um pj.Error retorna vazio, o que esconde o motivo do erro
    (ex.: PJSIP_ESESSIONINSECURE). info() monta a mensagem completa.
    """
    if isinstance(e, pj.Error):
        try:
            return e.info().strip() or str(e) or repr(e)
        except Exception:
            return str(e) or repr(e)
    return str(e)


# Faixa de erros PJMEDIA_AUDIODEV_ERRNO_START (420001..): falhas do
# dispositivo de som (PJMEDIA_EAUD_*), ex.: ALSA não abre o "default".
AUDIODEV_ERRNO_START = 420001
AUDIODEV_ERRNO_END = 421000


def is_audio_device_error(e):
    """True se o erro do pjsua2 for falha ao abrir/usar dispositivo de som."""
    if not isinstance(e, pj.Error):
        return False
    if AUDIODEV_ERRNO_START <= getattr(e, "status", 0) < AUDIODEV_ERRNO_END:
        return True
    reason = ""
    try:
        reason = (getattr(e, "reason", "") or "") + (getattr(e, "title", "") or "")
    except Exception:
        pass
    return any(k in reason.lower() for k in ("sound device", "audiodev", "snd_dev"))


def audio_error_hint(err_text=""):
    """Dica acionável para falha de dispositivo de áudio (PipeWire/ALSA)."""
    return (
        "O PJSIP usa a pilha ALSA da distribuição, que normalmente é um "
        "redirecionamento para PipeWire/PulseAudio.\n"
        "Em distros Arch-based (BigLinux, Manjaro...) verifique:\n"
        "  1. sudo pacman -S pipewire-alsa alsa-plugins alsa-utils\n"
        "  2. Teste fora do app: arecord -D default -f cd /dev/null e "
        "aplay -D default /dev/null\n"
        "  3. Em Configurações > Áudio, escolha outro dispositivo de "
        "captura/reprodução."
    )



COLOR_BG = THEMES["light"]["bg"]
COLOR_CARD = THEMES["light"]["card"]
COLOR_BORDER = THEMES["light"]["border"]
COLOR_PRIMARY = "#3B82F6"
COLOR_PRIMARY_DARK = THEMES["light"]["primary_dark"]
COLOR_SUCCESS = "#22C55E"
COLOR_DANGER = "#EF4444"
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



_ACTIVE_THEME = "light"


def active_theme():
    """Tema efetivamente em uso ("light"/"dark") após resolver "auto"."""
    return _ACTIVE_THEME


def set_theme(name):
    """Aplica a paleta de cores do tema, atualizando as globais COLOR_*.

    Aceita "auto": resolve seguindo a preferência do sistema operacional.
    """
    global COLOR_BG, COLOR_CARD, COLOR_BORDER, COLOR_PRIMARY_DARK
    global COLOR_TEXT, COLOR_MUTED, COLOR_LIST_EVEN, COLOR_LIST_ODD
    global COLOR_HEADER, COLOR_HEADER_CHIP, COLOR_KEYPAD_BG, COLOR_KEYPAD_FG
    global COLOR_TOOLTIP_BG, COLOR_TOOLTIP_FG, _ACTIVE_THEME
    key = name if name in THEMES else detect_system_theme()
    if key not in THEMES:
        key = "light"
    _ACTIVE_THEME = key
    t = THEMES[key]
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
    STATUS_COLORS.update(
        {
            "IDLE": COLOR_SUCCESS,
            "CALLING": COLOR_PRIMARY,
            "RINGING": COLOR_WARNING,
            "INCOMING": COLOR_DANGER,
            "IN_CALL": COLOR_SUCCESS,
            "HOLD": COLOR_WARNING,
        }
    )


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


# O Tk 8.6.12 (Ubuntu 22.04) tem um bug no fallback de fontes Xft:
# font.measure()/metrics() com glifos ausentes da fonte base (emoji e
# símbolos como ⏸ 📹 ↪) corrompem memória e segfaultam em Tk_FreeFont.
# Desenhar esses glifos (create_text) é seguro; apenas NÃO os medimos.
_FALLBACK_CHARS_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # emoji (plano suplementar)
    "\u2190-\u21FF"  # setas (↪ ↺)
    "\u2300-\u23FF"  # símbolos técnicos (⏸ ⏺)
    "\u2460-\u24FF"  # numerados em círculo
    "\u25A0-\u25FF"  # formas geométricas
    "\u2600-\u27BF"  # símbolos diversos + dingbats
    "\u2B00-\u2BFF"  # setas e símbolos suplementares
    "]"
)
_ZERO_WIDTH_RE = re.compile("[\uFE0F\u200D\u20E3]")


def _safe_measure_text(text):
    """Substitui glifos que exigem fallback por 'MM' antes de medir.

    'MM' aproxima a largura de um emoji, mantendo o tamanho do botão
    adequado sem disparar o bug de medição do Tk 8.6.12.
    """
    text = _ZERO_WIDTH_RE.sub("", text)
    return _FALLBACK_CHARS_RE.sub("MM", text)


_FONT_CACHE = {}


def _cached_font(spec):
    """tkfont.Font em cache por especificação.

    Evita criar/deletar fontes nomeadas a cada botão (churn desnecessário
    no Tk e nomes font1..fontN crescendo sem controle).
    """
    key = spec if isinstance(spec, str) else tuple(spec)
    f = _FONT_CACHE.get(key)
    if f is None:
        f = tkfont.Font(font=key)
        _FONT_CACHE[key] = f
    return f



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



class Toast(tk.Toplevel):
    """Feedback não modal para eventos informativos da interface."""

    def __init__(self, parent, message, duration=3000):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#1E293B")
        self.update_idletasks()
        width, height = 320, 58
        x = parent.winfo_rootx() + max(0, parent.winfo_width() - width - 18)
        y = parent.winfo_rooty() + max(0, parent.winfo_height() - height - 18)
        self.geometry(f"{width}x{height}+{x}+{y}")
        tk.Label(
            self,
            text=message,
            bg="#1E293B",
            fg="#F8FAFC",
            font=(pick_font(), 10),
            padx=14,
            pady=10,
            wraplength=290,
            justify=tk.LEFT,
        ).pack(expand=True, fill=tk.BOTH)
        self.after(duration, self.destroy)



class QosGraphWindow:
    """Janela leve de gráficos QoS usando apenas Canvas do Tkinter."""

    def __init__(self, parent, app):
        self.app = app
        self.win = tk.Toplevel(parent)
        self.win.title("Estatísticas de QoS")
        self.win.geometry("720x560")
        self.win.minsize(560, 420)
        self.win.transient(parent)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.status = ttk.Label(self.win, text="Sem dados de QoS", anchor="center")
        self.status.pack(fill=tk.X, padx=12, pady=(10, 4))
        self.canvas = tk.Canvas(
            self.win, bg=COLOR_CARD, highlightthickness=1,
            highlightbackground=COLOR_BORDER,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        self.toolbar = tk.Frame(self.win, bg=COLOR_BG)
        self.toolbar.pack(fill=tk.X, padx=12, pady=(0, 10))
        self._styled_button(
            "Exportar CSV", self.export_csv, COLOR_PRIMARY
        ).pack(side=tk.LEFT)
        self._job = None
        self.update()

    def _styled_button(self, text, command, color):
        return RoundedButton(
            self.toolbar, text=text, command=command, bg=color,
            fg="#FFFFFF", font=(pick_font(), 9, "bold"), padx=10, pady=5,
        )

    def update(self):
        if not self.win.winfo_exists():
            return
        self.draw()
        self._job = self.win.after(1000, self.update)

    def draw(self):
        self.canvas.delete("all")
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        metrics = (
            ("Jitter (ms)", "jitter", COLOR_PRIMARY),
            ("Perda (%)", "loss", COLOR_DANGER),
            ("RTT (ms)", "rtt", COLOR_SUCCESS),
        )
        history = self.app.qos_history
        has_data = any(history[key] for _, key, _ in metrics)
        if not has_data:
            self.canvas.create_text(
                width // 2, height // 2, text="Aguardando uma chamada com áudio...",
                fill=COLOR_MUTED, font=(pick_font(), 11),
            )
            return
        band = max(1, height // len(metrics))
        for index, (title, key, color) in enumerate(metrics):
            top = index * band
            bottom = min(height, top + band - 8)
            values = history[key]
            max_value = max(max(values), 1.0)
            self.canvas.create_text(
                10, top + 12, anchor="w", text=title,
                fill=COLOR_TEXT, font=(pick_font(), 9, "bold"),
            )
            self.canvas.create_line(8, bottom, width - 8, bottom, fill=COLOR_BORDER)
            if len(values) < 2:
                continue
            points = []
            for pos, value in enumerate(values):
                x = 10 + (width - 20) * pos / max(1, len(values) - 1)
                y = bottom - 8 - (bottom - top - 28) * min(value, max_value) / max_value
                points.extend((x, y))
            self.canvas.create_line(*points, fill=color, width=2, smooth=True)
        worst = self.app._qos_quality(self.app._latest_qos)
        labels = {"good": "Qualidade excelente", "medium": "Qualidade média", "bad": "Qualidade ruim"}
        self.status.config(text=labels[worst], foreground={"good": COLOR_SUCCESS, "medium": COLOR_WARNING, "bad": COLOR_DANGER}[worst])

    def export_csv(self):
        path = filedialog.asksaveasfilename(
            parent=self.win, title="Exportar log de QoS", defaultextension=".csv",
            initialfile="voice_neves_qos.csv", filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        try:
            rows = zip(
                self.app.qos_history["timestamp"],
                self.app.qos_history["jitter"],
                self.app.qos_history["loss"],
                self.app.qos_history["rtt"],
            )
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(("timestamp", "jitter_ms", "loss_pct", "rtt_ms"))
                writer.writerows(rows)
            self.app.show_toast("Log QoS exportado")
        except OSError as e:
            messagebox.showerror("QoS", f"Falha ao exportar CSV:\n{e}", parent=self.win)

    def close(self):
        if self._job is not None:
            try:
                self.win.after_cancel(self._job)
            except Exception:
                pass
        self.app.qos_graph_win = None
        self.win.destroy()


# =========================
# LOGGING
# =========================

def _native_video_handle(xid):
    """Cria um VideoWindowHandle apontando para uma janela nativa X11.

    O binding pjsua2 (SWIG 4.x) expõe WindowHandle.window como void* tipado,
    que não aceita um int -- e o hack antigo (c_int.from_address(int(h.type)))
    gravava no endereço 0 (int(h.type)==0), causando segfault em "Ver prévia".
    Setamos o type via constante do binding e gravamos o XID direto no struct
    C (pj::WindowHandle = { void* window; void* display; }) via ctypes.
    """
    import ctypes as _ct

    h = pj.VideoWindowHandle()
    try:
        h.type = pj.PJMEDIA_VID_DEV_HWND_TYPE_WINDOWS
    except Exception:
        pass
    wh = h.handle
    try:
        addr = int(wh.this)
        _ct.c_uint64.from_address(addr).value = int(xid)      # void *window
        _ct.c_uint64.from_address(addr + 8).value = 0         # void *display
    except Exception as e:
        logging.warning("Falha ao setar window handle de vídeo: %s", e)
    return h


# =========================
# ARMAZENAMENTO DE SENHAS
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
        self._pressed = False
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
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Button-1>", self._on_click)
        self.bind("<space>", self._on_click)
        self.bind("<Return>", self._on_click)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Configure>", self._draw)

    def _requested_size(self):
        f = _cached_font(self._font)
        tw = f.measure(_safe_measure_text(self._text))
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
        elif self._pressed:
            fill = self._darken(fill)
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
    def _darken(color, amount=0.16):
        try:
            if color and color.startswith("#") and len(color) == 7:
                r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
                return f"#{int(r * (1 - amount)):02X}{int(g * (1 - amount)):02X}{int(b * (1 - amount)):02X}"
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

    def _on_press(self, _event=None):
        if not self._disabled:
            self._pressed = True
            self._draw()

    def _on_release(self, _event=None):
        self._pressed = False
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
        self.root.geometry("520x820")
        self.root.minsize(460, 760)
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
        self.recorder = None
        self.recording = False
        self.record_path = ""
        self._record_number = ""
        self.incoming_call = None
        self.calls = {}
        self.held_calls = set()
        self.conf_active = False
        self.conf_media = {}
        self._moh = {}
        self._call_started = {}
        self._timer_job = None
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
        self.adv_win = None

        self.video_enabled = False
        self._has_video = False
        self.video_win = None
        self.video_box = None
        self.video_placeholder = None
        self.video_preview_frame = None
        self.video_preview_label = None
        self._preview = None
        self._remote_window = None
        self._screen_device_id = -1
        self._screen_shared = False
        self._video_fullscreen = False
        self.video_bandwidth_spin = None
        self.video_resolution_box = None
        self.video_info_label = None
        self.btn_screen_share = None

        self._main_tid = threading.get_ident()
        self._ui_queue = queue.Queue()
        self._presence = {}
        self._presence_buddies = []
        self._forward_timers = {}

        self._tray_icon = None
        self._tray_thread = None
        self._hotkeys = None
        self._theme_proc = None

        self.history = load_history()
        self.contacts_store = ContactsStore()
        self.contacts = self.contacts_store.load()
        self._contact_ringtone = ""
        self.contacts_win = None
        self.contact_edit_win = None
        self.contact_search = None
        self.contact_tree = None
        self._filtered_contacts = []

        self.config_data = load_config(secrets)
        cfg_font = str(self.config_data.get("font") or "").strip()
        if cfg_font:
            global _picked_font
            _picked_font = cfg_font
            self._font = cfg_font
        self.ldap_manager = LDAPManager(self, self.config_data.get("ldap", {}), secrets)
        self.zrtp_config = _clean_zrtp(self.config_data.get("zrtp"))
        self.zrtp_available = any(
            hasattr(pj, name) for name in ("PJMEDIA_HAS_ZRTP", "ZRTP", "ZrtpInfo")
        )
        self.zrtp_enabled = self.zrtp_config["enabled"] and self.zrtp_available
        self._zrtp_state = {}

        self.theme_name = self.config_data.get("theme", "auto")
        if self.theme_name != "auto" and self.theme_name not in THEMES:
            self.theme_name = "auto"
        set_theme(self.theme_name)

        self.pickup_code = (self.config_data.get("pickup_code") or "*8").strip() or "*8"
        self.autoanswer_code = (self.config_data.get("autoanswer_code") or "").strip()
        self.dnd_code = (self.config_data.get("dnd_code") or "").strip()
        self.forward_code = (self.config_data.get("forward_code") or "").strip()
        self.auto_answer = bool(self.config_data.get("auto_answer"))
        self.publish_presence = bool(self.config_data.get("publish_presence"))
        self._last_number = ""
        self.qos_graph_win = None
        self._latest_qos = None
        self.qos_history = {"timestamp": [], "jitter": [], "loss": [], "rtt": []}
        self._qos_max_points = 60
        self.zrtp_label = None

        # Backend SIP: pjsua2 disponível? Em Win/Mac fica None -- a UI abre mas
        # as chamadas são bloqueadas e o status mostra "Backend indisponível".
        self._sip_available = pj is not None

        # No Wayland o SDL2 usa o backend wayland por padrão, o que impede
        # embutir a prévia/o vídeo remoto numa janela X11 do Tk (Tk roda em
        # XWayland). Forçar o driver X11 faz o SDL_CreateWindowFrom(xid)
        # funcionar. Deve ser antes do libInit/libStart (o SDL init lá).
        os.environ.setdefault("SDL_VIDEODRIVER", "x11")

        self.init_pjsip()
        self.apply_saved_codecs()
        self.setup_ui()
        self.auto_register_accounts()
        self.update_call_ui()
        self._setup_tray()
        self._setup_hotkeys()
        self._start_theme_watcher()
        self.root.after(50, self.loop)
        if getattr(self, "_audio_warning", None):
            self.root.after(1200, self._show_audio_warning)

    def _show_audio_warning(self):
        """Aviso pós-boot quando a sondagem de áudio falhou na inicialização."""
        if not getattr(self, "_audio_warning", None):
            return
        logging.warning("Aviso de áudio ao usuário: %s", self._audio_warning)
        messagebox.showwarning("Problema de áudio detectado", self._audio_warning)
        self._audio_warning = None

    # =========================
    # PJSIP
    # =========================
    def init_pjsip(self):
        if not self._sip_available:
            self.endpoint = None
            logging.warning(
                "Backend SIP indisponível (pjsua2 não encontrado). "
                "App vai abrir apenas com a UI; chamadas/registro desativados."
            )
            return
        self.endpoint = pj.Endpoint()
        self.endpoint.libCreate()

        ep_cfg = pj.EpConfig()
        ep_cfg.logConfig.level = 5
        ep_cfg.logConfig.consoleLevel = 0
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            ep_cfg.logConfig.filename = os.path.join(DATA_DIR, "pjsua.log")
        except Exception as e:
            logging.warning("Não foi possível definir log do pjsua: %s", e)

        stun = str((self.config_data.get("nat") or {}).get("stun_server") or "")
        if stun:
            try:
                ep_cfg.uaConfig.stunServer.push_back(stun)
            except Exception as e:
                logging.warning("Não foi possível aplicar STUN (%s): %s", stun, e)

        self.endpoint.libInit(ep_cfg)

        self._udp_tid = None
        self._tls_tid = None
        try:
            tcfg = pj.TransportConfig()
            tcfg.port = 0
            self._udp_tid = self.endpoint.transportCreate(pj.PJSIP_TRANSPORT_UDP, tcfg)
        except Exception as e:
            logging.error("Erro ao criar transporte UDP: %s", e)

        if (self.config_data.get("security") or {}).get("tls"):
            self._create_tls_transport()

        self.endpoint.libStart()
        self._detect_video_support()
        self._detect_audio_support()

    def _try_open_sound(self, capture_dev, playback_dev):
        """Abre imediatamente o par cap/play (mesmo fluxo do makeCall do pjsua2).

        Retorna None em sucesso ou o texto do erro. Usa setSndDevMode(0) para
        forçar abertura imediata: setCaptureDev/setPlaybackDev sozinhos marcam
        PJSUA_SND_DEV_NO_IMMEDIATE_OPEN e NÃO testam a abertura real.
        """
        try:
            adm = self.endpoint.audDevManager()
            adm.setCaptureDev(capture_dev)
            adm.setPlaybackDev(playback_dev)
            adm.setSndDevMode(0)
            return None
        except Exception as e:
            return pj_error_text(e)

    def _detect_audio_support(self):
        self._has_audio = False
        self._audio_warning = None
        try:
            devs = list(self.endpoint.audDevManager().enumDev2())
        except Exception as e:
            devs = []
            logging.error("Não foi possível enumerar dispositivos de áudio: %s", e)

        if not devs:
            logging.critical(
                "NENHUM dispositivo de áudio PJSIP disponível (0). O toque não toca "
                "e as chamadas ficam mudas. Causa provável: pjsua2 compilado sem "
                "backend de áudio (ALSA/PulseAudio) ou ALSA sem dispositivos visíveis."
            )
            self._audio_warning = (
                "Nenhum dispositivo de áudio foi encontrado pelo PJSIP.\n"
                "As chamadas vão conectar SEM SOM."
            )
            return

        # Sondagem ativa do par padrão (-1/-2). Enumerar não basta: em distros
        # Arch-based (ex.: BigLinux) o mapeamento ALSA "default" -> PipeWire pode
        # estar quebrado mesmo listando dispositivos. O makeCall do pjsua2 abre
        # o som ANTES de enviar o INVITE (pjsua_call_make_call -> pjsua_set_snd_dev)
        # e falha na hora com erro apontando para src/pjsua2/call.cpp.
        err = self._try_open_sound(-1, -2)
        if err is None:
            self._has_audio = True
            logging.info(
                "PJSUA abriu o dispositivo padrão de áudio (%d disponíveis)", len(devs)
            )
            return

        logging.warning(
            "Dispositivo de áudio PADRÃO não abriu (%s). Tentando alternativos...", err
        )

        # Fallback 1: dispositivos duplex; Fallback 2: pares captura x playback.
        duplex = [i for i, d in enumerate(devs) if d.inputCount > 0 and d.outputCount > 0]
        caps = [i for i, d in enumerate(devs) if d.inputCount > 0]
        plays = [i for i, d in enumerate(devs) if d.outputCount > 0]
        candidates = [(i, i) for i in duplex]
        candidates += [(c, p) for c in caps for p in plays if c != p]

        last_err = err
        for cap_id, play_id in candidates:
            last_err = self._try_open_sound(cap_id, play_id)
            if last_err is None:
                self._has_audio = True
                logging.warning(
                    "Áudio funcionando com dispositivo alternativo: captura=%d ('%s'), "
                    "playback=%d ('%s')",
                    cap_id,
                    devs[cap_id].name,
                    play_id,
                    devs[play_id].name,
                )
                return

        # Nada abriu: usa dispositivo nulo para as chamadas ainda conectarem
        # (sem som) em vez do makeCall estourar erro em call.cpp.
        try:
            self.endpoint.audDevManager().setNullDev()
        except Exception as e:
            logging.error("Falha ao ativar dispositivo de áudio nulo: %s", e)
        hint = audio_error_hint(last_err)
        self._audio_warning = (
            "Não foi possível abrir nenhum dispositivo de áudio.\n"
            "As chamadas vão conectar SEM SOM.\n\n" + hint + f"\n\nÚltimo erro: {last_err}"
        )
        logging.critical(
            "NENHUM dispositivo de áudio pôde ser aberto. Chamadas ficarão mudas. "
            "Último erro: %s",
            last_err,
        )

    def _detect_video_support(self):
        try:
            self._has_video = self.endpoint.vidDevManager().getDevCount() > 0
        except Exception as e:
            self._has_video = False
            logging.warning("Não foi possível detectar suporte a vídeo: %s", e)
        if not self._has_video:
            logging.info("PJSUA sem dispositivos de vídeo; recursos de vídeo desativados")

    def _create_tls_transport(self):
        sec = self.config_data.get("security") or {}
        try:
            tcfg = pj.TransportConfig()
            tcfg.port = 0
            tls = tcfg.tlsConfig
            ca_file = str(sec.get("tls_ca_file") or "")
            try:
                tls.CaListFile = ca_file
            except (AttributeError, TypeError):
                tls.caListFile = ca_file
            tls.certFile = str(sec.get("tls_cert_file") or "")
            tls.privKeyFile = str(sec.get("tls_key_file") or "")
            tls.verifyServer = bool(sec.get("tls_ca_file"))
            self._tls_tid = self.endpoint.transportCreate(pj.PJSIP_TRANSPORT_TLS, tcfg)
            logging.info("Transporte TLS criado (id=%s)", self._tls_tid)
        except Exception as e:
            self._tls_tid = None
            logging.error(
                "Erro ao criar transporte TLS (verifique os arquivos de certificado): %s", e
            )

    # =========================
    # UI
    # =========================
    def setup_menu(self):
        menubar = tk.Menu(self.root)

        m_arquivo = tk.Menu(menubar, tearoff=0)
        m_arquivo.add_command(label="Exportar dados...", command=self.export_data)
        m_arquivo.add_command(label="Importar dados...", command=self.import_data)
        m_arquivo.add_separator()
        m_arquivo.add_command(label="Deletar Conta", accelerator="Ctrl+Shift+D", command=self.delete_account)
        m_arquivo.add_separator()
        m_arquivo.add_command(label="Sair", accelerator="Ctrl+Q", command=self.close)
        menubar.add_cascade(label="Arquivo", menu=m_arquivo)

        m_editar = tk.Menu(menubar, tearoff=0)
        m_editar.add_command(label="Limpar Campos", command=self.clear_fields)
        m_editar.add_command(label="Rediscar", accelerator="Ctrl+D", command=self.redial)
        m_editar.add_command(label="Mute/Unmute", command=self.toggle_mute)
        menubar.add_cascade(label="Editar", menu=m_editar)

        m_config = tk.Menu(menubar, tearoff=0)
        m_config.add_command(label="Configurações...", command=self.open_settings)
        m_config.add_command(label="Codecs...", command=self.open_codecs)
        m_config.add_command(label="Vídeo...", command=self.open_video)
        m_config.add_command(label="Segurança e NAT...", command=self.open_advanced)
        menubar.add_cascade(label="Config.", menu=m_config)

        m_exibir = tk.Menu(menubar, tearoff=0)
        m_exibir.add_command(label="Re-registrar Contas", command=self.auto_register_accounts)
        m_exibir.add_separator()
        self._theme_var = tk.BooleanVar(value=(active_theme() == "dark"))
        m_exibir.add_checkbutton(
            label="Tema Escuro", variable=self._theme_var, command=self.toggle_theme
        )
        m_exibir.add_separator()
        m_contatos = tk.Menu(menubar, tearoff=0)
        m_contatos.add_command(label="Diretório de Contatos...", command=self.open_contacts)
        m_contatos.add_separator()
        m_contatos.add_command(label="Novo Contato...", command=lambda: self.edit_contact(None))
        m_exibir.add_cascade(label="Contatos", menu=m_contatos)
        m_exibir.add_separator()
        m_exibir.add_command(label="Estatísticas de QoS...", command=self.open_qos_graph)
        menubar.add_cascade(label="Exibir", menu=m_exibir)

        m_recursos = tk.Menu(menubar, tearoff=0)
        m_recursos.add_command(label="DND (não perturbe)", command=self.dial_dnd)
        m_recursos.add_command(label="Encaminhar...", command=self.dial_forward)
        m_recursos.add_command(label="Código auto-atender", command=self.dial_autoanswer)
        m_recursos.add_separator()
        self._auto_answer_var = tk.BooleanVar(value=self.auto_answer)
        m_recursos.add_checkbutton(
            label="Auto-atender chamadas", variable=self._auto_answer_var,
            command=self.toggle_auto_answer,
        )
        menubar.add_cascade(label="Rec.", menu=m_recursos)

        m_historico = tk.Menu(menubar, tearoff=0)
        m_historico.add_command(label="Ver Histórico", command=self.show_history)
        m_historico.add_command(label="Limpar Histórico", command=self.clear_history)
        menubar.add_cascade(label="Hist.", menu=m_historico)

        m_ajuda = tk.Menu(menubar, tearoff=0)
        m_ajuda.add_command(label="Relatar problema...", command=self.report_problem)
        m_ajuda.add_command(label="Compartilhar ideia...", command=self.share_idea)
        m_ajuda.add_separator()
        m_ajuda.add_command(label="Sobre", command=self.show_about)
        menubar.add_cascade(label="Ajuda", menu=m_ajuda)

        self.root.config(menu=menubar)

        self.root.bind_all("<Control-s>", lambda e: self.open_settings())
        self.root.bind_all("<Control-q>", lambda e: self.close())
        self.root.bind_all("<Control-d>", lambda e: self.redial())

    def clear_fields(self):
        self.number.delete(0, tk.END)
        if self.settings_win is not None:
            for entry in (self.user, self.server, self.password):
                entry.delete(0, tk.END)

    def _contact_feedback(self, subject):
        email = CONTACT_EMAIL
        try:
            import urllib.parse

            webbrowser.open(
                f"mailto:{email}?subject={urllib.parse.quote(subject + ' - ' + APP_NAME)}"
            )
        except Exception as e:
            logging.warning("Não foi possível abrir o cliente de e-mail: %s", e)
        messagebox.showinfo(
            "Ajuda",
            f"Para {subject.lower()} sobre o {APP_NAME}, escreva para:\n\n"
            f"  {email}\n\n"
            f"Seu programa de e-mail foi aberto com o assunto preenchido.",
        )

    def report_problem(self):
        self._contact_feedback("Relatar problema")

    def share_idea(self):
        self._contact_feedback("Compartilhar ideia")

    def show_about(self):
        if getattr(self, "about_win", None) is not None and self.about_win.winfo_exists():
            self.about_win.lift()
            return
        win = tk.Toplevel(self.root)
        self.about_win = win
        win.title(f"Sobre — {APP_NAME}")
        win.geometry("520x560")
        win.resizable(False, False)
        win.transient(self.root)
        self._raise_window(win)

        container = ttk.Frame(win, padding=16)
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(3, weight=1)

        ttk.Label(container, text=f"📞  {APP_NAME}", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            container,
            text=(
                "Softphone SIP leve e seguro para chamadas de voz e vídeo, "
                "com criptografia SRTP/TLS, conferência de três vias, "
                "transferência de chamadas, gravação, histórico e agenda de "
                "contatos com favoritos."
            ),
            style="Muted.TLabel",
            wraplength=480,
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="ew", pady=(6, 10))
        ttk.Label(
            container,
            text=(
                f"Versão: {APP_VERSION}\n"
                f"Desenvolvedor: {APP_DEV}\n"
                f"Última atualização: {APP_UPDATED}\n"
                f"Contato: {CONTACT_EMAIL}"
            ),
            justify=tk.LEFT,
        ).grid(row=2, column=0, sticky="ew", pady=(0, 10))

        lic_frame = ttk.LabelFrame(container, text="Licença MIT")
        lic_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
        lic_frame.grid_columnconfigure(0, weight=1)
        lic_frame.grid_rowconfigure(0, weight=1)
        txt = tk.Text(
            lic_frame,
            wrap="word",
            height=12,
            relief="flat",
            background=THEMES[active_theme()]["card_bg"],
            foreground=COLOR_TEXT,
            font=(self._font, 9),
        )
        txt.grid(row=0, column=0, sticky="nsew", padx=(4, 0), pady=4)
        sb = ttk.Scrollbar(lic_frame, orient=tk.VERTICAL, command=txt.yview)
        sb.grid(row=0, column=1, sticky="ns", pady=4)
        txt.configure(yscrollcommand=sb.set)
        txt.insert("1.0", MIT_LICENSE)
        txt.configure(state=tk.DISABLED)

        self._styled_button(
            container, "Fechar", win.destroy, COLOR_PRIMARY, fg="#FFFFFF", pady=4
        ).grid(row=4, column=0, sticky="e")

        win.protocol("WM_DELETE_WINDOW", win.destroy)

    def show_toast(self, message, duration=3000):
        try:
            Toast(self.root, message, duration)
        except Exception as e:
            logging.debug("Não foi possível exibir toast: %s", e)

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

    def _start_theme_watcher(self):
        """Com tema "auto", segue ao vivo o claro/escuro do sistema."""
        if self.theme_name != "auto":
            return

        def _changed():
            try:
                new = detect_system_theme()
                if new != active_theme():
                    self.apply_theme("auto")
            except Exception:
                pass

        def _watch():
            try:
                proc = subprocess.Popen(
                    ["gsettings", "monitor", "org.gnome.desktop.interface", "color-scheme"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                self._theme_proc = proc
                for _line in proc.stdout:
                    self.root.after(0, _changed)
            except Exception:
                pass

        threading.Thread(target=_watch, daemon=True, name="theme-watch").start()

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
        for attr in ("settings_win", "codec_win", "history_win", "edit_win", "contacts_win", "contact_edit_win"):
            win = getattr(self, attr, None)
            if win is not None:
                try:
                    win.destroy()
                except tk.TclError:
                    pass
                setattr(self, attr, None)
        self._edit_entry = None
        self._build_main_ui(rebuild=True)

    def _apply_appearance_theme(self):
        name = self._appearance_theme.get()
        if name == self.theme_name:
            return
        self.theme_name = name
        self.config_data["theme"] = name
        save_config(self.config_data)
        if getattr(self, "_theme_var", None) is not None:
            self._theme_var.set(name == "dark")
        # apply_theme reconstrói a UI e fecha a janela de configurações.
        self.apply_theme(name)
        self.open_settings()

    def _apply_appearance_font(self):
        name = (self._appearance_font.get() or "").strip()
        if not name:
            return
        global _picked_font
        _picked_font = name
        self._font = name
        self.config_data["font"] = name
        save_config(self.config_data)
        self.apply_theme(self.theme_name)
        self.open_settings()
        self.show_toast(f"Fonte {name} aplicada")

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
        # Status de criptografia/QoS: maior e em negrito para leitura confortável
        style.configure("Status.TLabel", font=(self._font, 12, "bold"))

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
            font=(self._font, 14, "bold"),
            padx=16,
            pady=13,
        ).pack(side=tk.LEFT)

        self.timer_label = tk.Label(
            header,
            text="",
            bg=COLOR_HEADER,
            fg="#FFFFFF",
            font=("TkFixedFont", 11, "bold"),
            padx=10,
            pady=3,
        )
        self.timer_label.pack(side=tk.LEFT, pady=10)

        status_panel = tk.Frame(header, bg=COLOR_HEADER)
        status_panel.pack(side=tk.RIGHT, padx=14)

        self.status_canvas = tk.Canvas(
            status_panel, width=20, height=20, bg=COLOR_HEADER, highlightthickness=0
        )
        self.status_dot = self.status_canvas.create_oval(3, 3, 17, 17, fill=STATUS_COLORS["IDLE"], outline="")
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
        acc_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        container.grid_rowconfigure(0, weight=0)
        acc_frame.grid_columnconfigure(0, weight=1)

        list_frame = tk.Frame(acc_frame, bg=COLOR_BG)
        list_frame.grid(row=0, column=0, sticky="nsew")
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(
            list_frame,
            height=3,
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
            acc_btns, "Editar conta", self.edit_account,
            COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG, pady=6
        )
        self.btn_edit.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ToolTip(self.btn_edit, "Editar a conta selecionada")

        self.btn_delete = self._styled_button(
            acc_btns, "Deletar conta", self.delete_account,
            COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG, pady=6
        )
        self.btn_delete.grid(row=0, column=1, sticky="ew", padx=2, pady=2)

        # ===== Discagem =====
        dial_frame = ttk.LabelFrame(container, text="Discagem")
        dial_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        container.grid_rowconfigure(1, weight=1)
        dial_frame.grid_columnconfigure(0, weight=1)
        dial_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(dial_frame, text="Número").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        self.number = ttk.Entry(dial_frame)
        self.number.grid(row=0, column=1, sticky="ew", pady=3)
        ToolTip(self.number, "Ramal ou número para discar (ex.: 3000)")
        self.number.bind("<Return>", lambda e: self.make_call())

        keypad = tk.Frame(dial_frame, bg=COLOR_BG)
        keypad.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(8, 4))
        for c in range(3):
            keypad.grid_columnconfigure(c, weight=1, uniform="keypad-columns")
        for r in range(4):
            keypad.grid_rowconfigure(r, weight=1, uniform="keypad-rows")
        for i, key in enumerate("123456789*0#"):
            r, c = divmod(i, 3)
            self._styled_button(
                keypad, key, lambda k=key: self.on_keypad_press(k),
                COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG, pady=6,
            ).grid(row=r, column=c, sticky="nsew", padx=2, pady=2)

        feature_btns = tk.Frame(dial_frame, bg=COLOR_BG)
        feature_btns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(2, 2))
        for c in range(3):
            feature_btns.grid_columnconfigure(c, weight=1, uniform="feature-columns")

        self.btn_hold = self._styled_button(
            feature_btns, "⏸  Espera", self.toggle_hold,
            COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG, pady=6
        )
        self.btn_hold.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ToolTip(self.btn_hold, "Colocar / retirar a chamada em espera")

        self.btn_transfer = self._styled_button(
            feature_btns, "↪  Transf.", self.open_transfer,
            COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG, pady=6
        )
        self.btn_transfer.grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        ToolTip(self.btn_transfer, "Transferir a chamada para outro ramal (cega ou assistida)")

        self.btn_redial = self._styled_button(
            feature_btns, "↺  Rediscar", self.redial,
            COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG, pady=6
        )
        self.btn_redial.grid(row=0, column=2, sticky="ew", padx=2, pady=2)
        ToolTip(self.btn_redial, "Ligar novamente para o último número discado (Ctrl+D)")

        self.favorites_frame = tk.Frame(dial_frame, bg=COLOR_BG)
        self.favorites_frame.grid(row=3, column=0, columnspan=2, sticky="ew", padx=12, pady=(2, 2))
        self.refresh_favorites()

        call_btns = tk.Frame(dial_frame, bg=COLOR_BG)
        call_btns.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(2, 2))
        for c in range(2):
            call_btns.grid_columnconfigure(c, weight=1)

        self.btn_call = self._styled_button(
            call_btns, "📞  Ligar", self.make_call,
            COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG, pady=6
        )
        self.btn_call.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ToolTip(self.btn_call, "Iniciar chamada para o número informado")

        self.btn_answer = self._styled_button(
            call_btns, "✅  Atender", self.answer,
            COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG, pady=6
        )
        self.btn_answer.grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        ToolTip(self.btn_answer, "Atender a chamada recebida; com chamada em curso, iniciar/encerrar conferência")

        media_btns = tk.Frame(dial_frame, bg=COLOR_BG)
        media_btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 4))
        for c in range(3):
            media_btns.grid_columnconfigure(c, weight=1)

        self.btn_mute = self._styled_button(
            media_btns, "Mute", self.toggle_mute, COLOR_WARNING, fg=COLOR_TEXT
        )
        self.btn_mute.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ToolTip(self.btn_mute, "Silenciar / reativar o microfone")

        self.btn_record = self._styled_button(
            media_btns, "⏺  Gravar", self.toggle_record,
            COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG, pady=6
        )
        self.btn_record.grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        ToolTip(self.btn_record, "Gravar a chamada atual (salva em ~/Music/VoiceNeves)")

        self.btn_video = self._styled_button(
            media_btns, "📹  Vídeo", self.toggle_video,
            COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG, pady=6
        )
        self.btn_video.grid(row=0, column=2, sticky="ew", padx=2, pady=2)
        ToolTip(self.btn_video, "Ligar / desligar o vídeo na chamada")

        active_frame = ttk.LabelFrame(dial_frame, text="Chamadas ativas")
        active_frame.grid(row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=(4, 8))
        active_frame.grid_columnconfigure(0, weight=1)
        active_frame.grid_columnconfigure(1, weight=1)
        self.call_switch_box = ttk.Combobox(active_frame, state="readonly")
        self.call_switch_box.grid(row=0, column=0, sticky="ew", padx=(4, 4), pady=4)
        self.btn_alternate = self._styled_button(
            active_frame, "Alternar", self.alternate_call, COLOR_PRIMARY
        )
        self.btn_alternate.grid(row=0, column=1, sticky="ew", padx=(4, 4), pady=4)
        ToolTip(self.btn_alternate, "Alternar para a chamada selecionada acima")

        self.qos_label = ttk.Label(
            active_frame, text="", style="Status.TLabel", anchor="center"
        )
        self.qos_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 6))
        self.zrtp_label = ttk.Label(active_frame, text="Cripto: —", style="Status.TLabel", anchor="center")
        self.zrtp_label.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 6))
        ToolTip(
            self.zrtp_label,
            "Estado da criptografia de mídia. Configure SRTP (SDES/DTLS) em "
            "Configurações > Avançado > Segurança e NAT.",
        )
        self._update_zrtp_ui()

    def _styled_button(self, parent, text, command, color, fg="#FFFFFF", **kw):
        opts = {
            "bg": color,
            "fg": fg,
            "font": (self._font, 10, "bold"),
            "padx": 10,
            "pady": 8,
            "radius": 12,
        }
        opts.update(kw)
        return RoundedButton(parent, text=text, command=command, **opts)

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
            win.geometry("600x640")
            win.minsize(520, 500)
            win.transient(self.root)
            win.protocol("WM_DELETE_WINDOW", self._close_settings)
            self.settings_win = win
            self._build_settings_ui(win)
            self.load_devices()

    def _close_settings(self):
        if self.settings_win is not None:
            self.settings_win.destroy()
            self.settings_win = None

    def open_video(self):
        if self.video_win is not None:
            try:
                self.video_win.deiconify()
                self.video_win.lift()
            except tk.TclError:
                self.video_win = None
        if self.video_win is None:
            win = tk.Toplevel(self.root)
            win.title("Vídeo")
            win.geometry("560x820")
            win.minsize(520, 740)
            win.transient(self.root)
            win.protocol("WM_DELETE_WINDOW", self._close_video)
            self.video_win = win
            self._build_video_ui(win)
            self.load_devices()
        if self.video_win is not None:
            try:
                self.video_win.lift()
            except tk.TclError:
                pass

    def _close_video(self):
        self._stop_preview()
        if self._remote_window is not None:
            try:
                self._remote_window.hide()
            except Exception:
                pass
            self._remote_window = None
        if self.video_win is not None:
            try:
                self.video_win.destroy()
            except tk.TclError:
                pass
            self.video_win = None

    def _build_video_ui(self, win):
        container = ttk.Frame(win, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        call_frame = ttk.LabelFrame(container, text="Vídeo da chamada")
        call_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        call_frame.grid_columnconfigure(0, weight=1)
        call_frame.grid_rowconfigure(0, weight=1, minsize=320)
        call_frame.grid_rowconfigure(1, weight=0)

        self.video_box = tk.Frame(call_frame, bg="black", width=420, height=360)
        self.video_box.grid(row=0, column=0, sticky="nsew")
        self.video_box.grid_propagate(False)
        self.video_placeholder = tk.Label(
            self.video_box, text="Vídeo desligado", bg="black", fg="#888888"
        )
        self.video_placeholder.pack(expand=True, fill=tk.BOTH)

        video_toolbar = tk.Frame(call_frame, bg=COLOR_BG)
        video_toolbar.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        for c in range(3):
            video_toolbar.grid_columnconfigure(c, weight=1)
        self.btn_screen_share = self._styled_button(
            video_toolbar, "🖥  Compartilhar tela", self._toggle_screen_sharing,
            COLOR_PRIMARY, pady=5
        )
        self.btn_screen_share.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._styled_button(
            video_toolbar, "Tela cheia", self._toggle_video_fullscreen,
            COLOR_MUTED, pady=5
        ).grid(row=0, column=1, sticky="ew", padx=4)
        self._styled_button(
            video_toolbar, "Tirar foto", self._take_video_snapshot,
            COLOR_MUTED, pady=5
        ).grid(row=0, column=2, sticky="ew", padx=(4, 0))

        cam_frame = ttk.LabelFrame(container, text="Câmera")
        cam_frame.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        cam_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(cam_frame, text="Câmera").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        self.video_devices = ttk.Combobox(cam_frame, state="readonly")
        self.video_devices.grid(row=0, column=1, sticky="ew", pady=3)
        ToolTip(self.video_devices, "Câmera usada nas chamadas de vídeo (padrão = primeira disponível)")

        cam_btns = tk.Frame(cam_frame, bg=COLOR_BG)
        cam_btns.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 4))
        for c in range(3):
            cam_btns.grid_columnconfigure(c, weight=1)

        self.btn_cam_apply = self._styled_button(
            cam_btns, "Aplicar câmera", self.apply_camera, COLOR_PRIMARY
        )
        self.btn_cam_apply.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.btn_video_preview = self._styled_button(
            cam_btns, "Ver prévia", self._toggle_preview, COLOR_MUTED
        )
        self.btn_video_preview.grid(row=0, column=1, sticky="ew", padx=4)
        self.btn_video_preview_close = self._styled_button(
            cam_btns, "Fechar prévia", self._stop_preview, COLOR_MUTED
        )
        self.btn_video_preview_close.grid(row=0, column=2, sticky="ew", padx=(4, 0))
        self.btn_video_mirror = self._styled_button(
            cam_btns, "🪞 Espelhar", self._toggle_mirror, COLOR_MUTED
        )
        self.btn_video_mirror.grid(row=0, column=3, sticky="ew", padx=(4, 0))

        cam_frame.grid_rowconfigure(2, weight=1, minsize=200)
        # Área-preta que cresce com a janela; o quadro de vídeo fica centrado
        # dentro dela mantendo 16:9 (letterbox simétrico).
        self.video_preview_area = tk.Frame(cam_frame, bg="black")
        self.video_preview_area.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(4, 4))
        self._preview_fit_job = None
        self.video_preview_area.bind("<Configure>", self._on_preview_area_configure)
        self.video_preview_frame = tk.Frame(
            self.video_preview_area, bg="black", width=480, height=270
        )
        self.video_preview_frame.place(x=0, y=0)
        self.video_preview_label = tk.Label(
            self.video_preview_frame, text="Prévia desligada", bg="black", fg="#888888"
        )
        self.video_preview_label.pack(expand=True, fill=tk.BOTH)

        settings_frame = ttk.LabelFrame(container, text="Qualidade de vídeo")
        settings_frame.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        settings_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(settings_frame, text="Resolução").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        self.video_resolution_box = ttk.Combobox(
            settings_frame, state="readonly", values=("auto", "640x480", "1280x720", "1920x1080")
        )
        self.video_resolution_box.set((self.config_data.get("video") or {}).get("video_resolution", "auto"))
        self.video_resolution_box.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(settings_frame, text="Largura de banda (kbps)").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        self.video_bandwidth_spin = ttk.Spinbox(settings_frame, from_=0, to=10000, increment=64, width=10)
        self.video_bandwidth_spin.set(str((self.config_data.get("video") or {}).get("video_bandwidth", 0)))
        self.video_bandwidth_spin.grid(row=1, column=1, sticky="w", pady=3)
        self._styled_button(
            settings_frame, "Aplicar qualidade", self._save_video_settings, COLOR_PRIMARY, pady=5
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 4))
        self.video_info_label = ttk.Label(settings_frame, text="", style="Muted.TLabel")
        self.video_info_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 4))

    def _make_scroll_tab(self, notebook, title):
        """Cria uma aba rolável no Notebook e devolve o frame interno."""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text=title)
        canvas = tk.Canvas(tab, bg=COLOR_BG, highlightthickness=0)
        vsb = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        win_id = canvas.create_window(0, 0, anchor="nw", window=inner)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))

        def _wheel(e):
            try:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            except tk.TclError:
                pass

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        inner.grid_columnconfigure(0, weight=1)
        return inner

    def _build_settings_ui(self, win):
        container = ttk.Frame(win, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        try:
            ttk.Style().configure("TNotebook", background=COLOR_BG, borderwidth=0)
            ttk.Style().configure(
                "TNotebook.Tab", background=COLOR_CARD, foreground=COLOR_TEXT,
                padding=(14, 7), font=(self._font, 10, "bold"),
            )
            ttk.Style().map(
                "TNotebook.Tab",
                background=[("selected", COLOR_PRIMARY)],
                foreground=[("selected", "#FFFFFF")],
            )
        except Exception:
            pass

        nb = ttk.Notebook(container)
        nb.grid(row=0, column=0, sticky="nsew")
        tab_contas = self._make_scroll_tab(nb, "Contas")
        tab_audio = self._make_scroll_tab(nb, "Áudio")
        tab_recursos = self._make_scroll_tab(nb, "Recursos")
        tab_ldap = self._make_scroll_tab(nb, "LDAP")
        tab_aparencia = self._make_scroll_tab(nb, "Aparência")

        acc_frame = ttk.LabelFrame(tab_contas, text="Adicionar conta")
        acc_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 10))
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

        audio_frame = ttk.LabelFrame(tab_audio, text="Áudio")
        audio_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 10))
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

        feat_frame = ttk.LabelFrame(tab_recursos, text="Códigos de feature")
        feat_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 10))
        feat_frame.grid_columnconfigure(1, weight=1)

        for r, (label, attr, tip) in enumerate((
            ("Captura (pickup)", "pickup_code", "Código para capturar chamada de outro ramal (ex.: *8)"),
            ("Auto-atender (código)", "autoanswer_code", "Código do PABX para auto-atender (vazio = desativado)"),
            ("DND (não perturbe)", "dnd_code", "Código do PABX para ativar/desativar não perturbe"),
            ("Encaminhar", "forward_code", "Código do PABX para encaminhamento de chamadas"),
        )):
            ttk.Label(feat_frame, text=label).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=3)
            entry = ttk.Entry(feat_frame)
            entry.insert(0, getattr(self, attr))
            entry.grid(row=r, column=1, sticky="ew", pady=3)
            setattr(self, f"feat_{attr}", entry)
            ToolTip(entry, tip)

        self.feat_auto_answer = tk.BooleanVar(value=self.auto_answer)
        ttk.Checkbutton(
            feat_frame, text="Atender chamadas automaticamente (auto-answer no app)",
            variable=self.feat_auto_answer,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=3)

        self.feat_publish_presence = tk.BooleanVar(value=self.publish_presence)
        ttk.Checkbutton(
            feat_frame, text="Publicar minha presença (online/ocupado)",
            variable=self.feat_publish_presence,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=3)

        self._styled_button(
            feat_frame, "💾  Salvar recursos", self._save_feature_codes, COLOR_SUCCESS
        ).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        ttk.Label(
            feat_frame,
            text="ZRTP foi movido para Segurança e NAT (menu Config. → Segurança e NAT).",
            style="Muted.TLabel", wraplength=380, justify=tk.LEFT,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ldap_frame = ttk.LabelFrame(tab_ldap, text="LDAP corporativo")
        ldap_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 10))
        ldap_frame.grid_columnconfigure(1, weight=1)
        ldap_cfg = self.config_data.get("ldap") or {}
        self.ldap_enabled_var = tk.BooleanVar(value=bool(ldap_cfg.get("enabled")))
        ttk.Checkbutton(
            ldap_frame, text="Ativar agenda corporativa LDAP", variable=self.ldap_enabled_var
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=3)
        for r, (label, key) in enumerate(
            (("Servidor", "server"), ("Base DN", "base_dn"), ("Bind DN", "bind_dn"), ("Filtro", "search_filter")),
            start=1,
        ):
            ttk.Label(ldap_frame, text=label).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=3)
            field = ttk.Entry(ldap_frame)
            field.insert(0, ldap_cfg.get(key, ""))
            field.grid(row=r, column=1, sticky="ew", pady=3)
            setattr(self, f"ldap_{key}_entry", field)
        ttk.Label(ldap_frame, text="Senha bind").grid(row=5, column=0, sticky="w", padx=(0, 8), pady=3)
        self.ldap_bind_password_entry = ttk.Entry(ldap_frame, show="*")
        self.ldap_bind_password_entry.grid(row=5, column=1, sticky="ew", pady=3)
        ToolTip(self.ldap_bind_password_entry, "Armazenada no keyring como ldap_bind")
        ttk.Label(ldap_frame, text="Intervalo (s)").grid(row=6, column=0, sticky="w", padx=(0, 8), pady=3)
        self.ldap_interval_spin = ttk.Spinbox(ldap_frame, from_=60, to=86400, width=10)
        self.ldap_interval_spin.set(str(ldap_cfg.get("sync_interval", 3600)))
        self.ldap_interval_spin.grid(row=6, column=1, sticky="w", pady=3)
        ldap_buttons = tk.Frame(ldap_frame, bg=COLOR_BG)
        ldap_buttons.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(6, 3))
        ldap_buttons.grid_columnconfigure(0, weight=1)
        ldap_buttons.grid_columnconfigure(1, weight=1)
        self._styled_button(ldap_buttons, "Testar conexão", self.test_ldap, COLOR_PRIMARY, pady=5).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        self._styled_button(ldap_buttons, "Sincronizar agora", self.sync_ldap_now, COLOR_MUTED, pady=5).grid(
            row=0, column=1, sticky="ew", padx=(4, 0)
        )

        # Aba Aparência: tema e fonte da interface
        app_frame = ttk.LabelFrame(tab_aparencia, text="Aparência")
        app_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 10))
        app_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(app_frame, text="Tema").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        theme_box = tk.Frame(app_frame, bg=COLOR_BG)
        theme_box.grid(row=0, column=1, sticky="w", pady=3)
        self._appearance_theme = tk.StringVar(value=self.theme_name)
        ttk.Radiobutton(
            theme_box, text="💻  Automático", value="auto",
            variable=self._appearance_theme, command=self._apply_appearance_theme,
        ).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Radiobutton(
            theme_box, text="☀️  Claro", value="light",
            variable=self._appearance_theme, command=self._apply_appearance_theme,
        ).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Radiobutton(
            theme_box, text="🌙  Escuro", value="dark",
            variable=self._appearance_theme, command=self._apply_appearance_theme,
        ).pack(side=tk.LEFT)

        ttk.Label(app_frame, text="Fonte da interface").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        fams = set(tkfont.families())
        font_values = [f for f in FONT_CANDIDATES if f in fams]
        if self._font not in font_values:
            font_values.insert(0, self._font)
        self._appearance_font = ttk.Combobox(app_frame, values=font_values)
        self._appearance_font.set(self._font)
        self._appearance_font.grid(row=1, column=1, sticky="ew", pady=3)
        ToolTip(
            self._appearance_font,
            "Fonte usada em toda a interface. A mudança se aplica ao clicar em Aplicar.",
        )

        self._styled_button(
            app_frame, "💾  Aplicar e salvar fonte", self._apply_appearance_font, COLOR_SUCCESS
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 4))
        ttk.Label(
            app_frame,
            text="A fonte é aplicada à interface inteira e a janela é reaberta com o novo visual.",
            style="Muted.TLabel", wraplength=420, justify=tk.LEFT,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 4))

        links = tk.Frame(container, bg=COLOR_BG)
        links.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for c in range(3):
            links.grid_columnconfigure(c, weight=1)
        self._styled_button(links, "🎵  Codecs", self.open_codecs, COLOR_MUTED).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        self._styled_button(links, "📹  Vídeo", self.open_video, COLOR_MUTED).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        self._styled_button(links, "🔒  Segurança e NAT", self.open_advanced, COLOR_MUTED).grid(
            row=0, column=2, sticky="ew", padx=(4, 0)
        )

    def _save_ldap_settings(self):
        try:
            interval = max(60, int(self.ldap_interval_spin.get()))
        except (TypeError, ValueError):
            interval = 3600
        cfg = {
            "enabled": bool(self.ldap_enabled_var.get()),
            "server": self.ldap_server_entry.get().strip(),
            "base_dn": self.ldap_base_dn_entry.get().strip(),
            "bind_dn": self.ldap_bind_dn_entry.get().strip(),
            "search_filter": self.ldap_search_filter_entry.get().strip() or "(objectClass=person)",
            "attributes": (self.config_data.get("ldap") or {}).get("attributes", {}),
            "sync_interval": interval,
            "cache_file": (self.config_data.get("ldap") or {}).get("cache_file", "ldap_cache.json"),
        }
        bind_password = self.ldap_bind_password_entry.get()
        if bind_password:
            secrets.set("ldap_bind", bind_password)
        self.config_data["ldap"] = _clean_ldap(cfg)
        save_config(self.config_data)
        if self.ldap_manager is not None:
            self.ldap_manager.close()
        self.ldap_manager = LDAPManager(self, self.config_data["ldap"], secrets)

    def test_ldap(self):
        self._save_ldap_settings()
        if self.ldap_manager is None or not self.config_data["ldap"]["enabled"]:
            self.show_toast("LDAP está desativado")
            return
        threading.Thread(target=self.ldap_manager.sync, name="ldap-test", daemon=True).start()
        self.show_toast("Teste LDAP iniciado em segundo plano")

    def sync_ldap_now(self):
        self._save_ldap_settings()
        if self.ldap_manager is not None:
            threading.Thread(target=self.ldap_manager.sync, name="ldap-manual-sync", daemon=True).start()
        self.show_toast("Sincronização LDAP iniciada")

    def _update_ldap_ui(self):
        if self.contacts_win is not None:
            self._filter_contacts()

    def _save_feature_codes(self):
        if self.settings_win is None:
            return
        self.config_data["pickup_code"] = self.feat_pickup_code.get().strip()
        self.config_data["autoanswer_code"] = self.feat_autoanswer_code.get().strip()
        self.config_data["dnd_code"] = self.feat_dnd_code.get().strip()
        self.config_data["forward_code"] = self.feat_forward_code.get().strip()
        self.config_data["auto_answer"] = bool(self.feat_auto_answer.get())
        self.config_data["publish_presence"] = bool(self.feat_publish_presence.get())
        save_config(self.config_data)
        self.pickup_code = self.config_data["pickup_code"] or "*8"
        self.autoanswer_code = self.config_data["autoanswer_code"]
        self.dnd_code = self.config_data["dnd_code"]
        self.forward_code = self.config_data["forward_code"]
        self.auto_answer = self.config_data["auto_answer"]
        self.publish_presence = self.config_data["publish_presence"]
        if hasattr(self, "_auto_answer_var"):
            self._auto_answer_var.set(self.auto_answer)
        messagebox.showinfo("Recursos", "Códigos de feature salvos.", parent=self.settings_win)

    # =========================
    # =========================
    # SEGURANÇA E NAT (avançado)
    # =========================
    def open_advanced(self):
        if self.adv_win is not None:
            try:
                self.adv_win.deiconify()
                self.adv_win.lift()
            except tk.TclError:
                self.adv_win = None
        if self.adv_win is None:
            win = tk.Toplevel(self.root)
            win.title("Segurança e NAT")
            win.geometry("460x620")
            win.minsize(420, 610)
            win.transient(self.root)
            win.protocol("WM_DELETE_WINDOW", self._close_advanced)
            self.adv_win = win
            self._build_advanced_ui(win)
        if self.adv_win is not None:
            try:
                self.adv_win.lift()
            except tk.TclError:
                pass

    def _close_advanced(self):
        if self.adv_win is not None:
            try:
                self.adv_win.destroy()
            except tk.TclError:
                pass
            self.adv_win = None

    def _build_advanced_ui(self, win):
        container = ttk.Frame(win, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_columnconfigure(0, weight=1)

        adv = ttk.LabelFrame(container, text="Segurança e NAT")
        adv.grid(row=0, column=0, sticky="nsew")
        adv.grid_columnconfigure(1, weight=1)

        nat = self.config_data.get("nat") or {}
        sec = self.config_data.get("security") or {}
        srtp_labels = {
            "disabled": "Desabilitado",
            "optional": "Opcional",
            "mandatory": "Obrigatório",
        }

        r = 0
        ttk.Label(adv, text="Servidor STUN").grid(row=r, column=0, sticky="w", padx=(0, 8), pady=3)
        self.adv_stun = ttk.Entry(adv)
        self.adv_stun.insert(0, nat.get("stun_server", ""))
        self.adv_stun.grid(row=r, column=1, sticky="ew", pady=3)
        ToolTip(self.adv_stun, "Servidor STUN para atravessar NAT (ex.: stun.cloudflare.com:3478). Vazio = sem STUN.")

        r += 1
        self.adv_ice = tk.BooleanVar(value=_as_bool(nat.get("ice")))
        ttk.Checkbutton(adv, text="Habilitar ICE (recomendado com STUN/TURN)",
                        variable=self.adv_ice).grid(row=r, column=0, columnspan=2, sticky="w", pady=3)

        r += 1
        self.adv_turn_enabled = tk.BooleanVar(value=_as_bool(nat.get("turn_enabled")))
        ttk.Checkbutton(adv, text="Habilitar TURN (reencaminhamento de mídia)",
                        variable=self.adv_turn_enabled).grid(row=r, column=0, columnspan=2, sticky="w", pady=3)

        r += 1
        ttk.Label(adv, text="Servidor TURN").grid(row=r, column=0, sticky="w", padx=(0, 8), pady=3)
        self.adv_turn_server = ttk.Entry(adv)
        self.adv_turn_server.insert(0, nat.get("turn_server", ""))
        self.adv_turn_server.grid(row=r, column=1, sticky="ew", pady=3)

        r += 1
        ttk.Label(adv, text="Usuário TURN").grid(row=r, column=0, sticky="w", padx=(0, 8), pady=3)
        self.adv_turn_user = ttk.Entry(adv)
        self.adv_turn_user.insert(0, nat.get("turn_user", ""))
        self.adv_turn_user.grid(row=r, column=1, sticky="ew", pady=3)

        r += 1
        ttk.Label(adv, text="Senha TURN").grid(row=r, column=0, sticky="w", padx=(0, 8), pady=3)
        self.adv_turn_password = ttk.Entry(adv, show="*")
        self.adv_turn_password.grid(row=r, column=1, sticky="ew", pady=3)
        ToolTip(self.adv_turn_password, "Nova senha TURN (vazio = manter a atual, guardada no cofre de senhas)")

        r += 1
        self.adv_tls = tk.BooleanVar(value=_as_bool(sec.get("tls")))
        ttk.Checkbutton(adv, text="Usar TLS (SIPS) nas contas",
                        variable=self.adv_tls).grid(row=r, column=0, columnspan=2, sticky="w", pady=3)

        for label, short, key in (
            ("Arquivo CA (opcional)", "tls_ca", "tls_ca_file"),
            ("Certificado (opcional)", "tls_cert", "tls_cert_file"),
            ("Chave privada (opcional)", "tls_key", "tls_key_file"),
        ):
            r += 1
            ttk.Label(adv, text=label).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=3)
            row_frame = tk.Frame(adv, bg=COLOR_BG)
            row_frame.grid(row=r, column=1, sticky="ew", pady=3)
            row_frame.grid_columnconfigure(0, weight=1)
            entry = ttk.Entry(row_frame)
            entry.insert(0, sec.get(key, ""))
            entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
            setattr(self, f"adv_{short}", entry)
            self._styled_button(
                row_frame, "…", lambda e=entry: self._pick_file(e), COLOR_MUTED
            ).grid(row=0, column=1)

        r += 1
        ttk.Label(adv, text="SRTP").grid(row=r, column=0, sticky="w", padx=(0, 8), pady=3)
        self.adv_srtp = ttk.Combobox(
            adv, state="readonly",
            values=[srtp_labels[k] for k in ("disabled", "optional", "mandatory")],
        )
        self.adv_srtp.set(srtp_labels.get(str(sec.get("srtp") or "disabled"), "Desabilitado"))
        self.adv_srtp.grid(row=r, column=1, sticky="ew", pady=3)
        ToolTip(self.adv_srtp, "SRTP protege o áudio da chamada. 'Obrigatório' exige SRTP em todas as chamadas.")

        r += 1
        self.adv_srtp_tls = tk.BooleanVar(value=_as_bool(sec.get("srtp_tls_only")))
        ttk.Checkbutton(adv, text="SRTP somente com TLS (SIPS)",
                        variable=self.adv_srtp_tls).grid(row=r, column=0, columnspan=2, sticky="w", pady=3)

        r += 1
        ttk.Separator(adv).grid(row=r, column=0, columnspan=2, sticky="ew", pady=(10, 4))

        r += 1
        ttk.Label(adv, text="ZRTP (criptografia de mídia ponto a ponto)",
                  style="Title.TLabel").grid(row=r, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.feat_zrtp_enabled = tk.BooleanVar(value=self.zrtp_config["enabled"])
        self.feat_zrtp_sas = tk.BooleanVar(value=self.zrtp_config["sas_required"])
        self.feat_zrtp_allow = tk.BooleanVar(value=self.zrtp_config["allow_unencrypted"])
        r += 1
        ttk.Checkbutton(adv, text="Habilitar ZRTP (se disponível no PJSIP)",
                        variable=self.feat_zrtp_enabled).grid(row=r, column=0, columnspan=2, sticky="w", pady=3)
        r += 1
        ttk.Checkbutton(adv, text="Exigir confirmação SAS",
                        variable=self.feat_zrtp_sas).grid(row=r, column=0, columnspan=2, sticky="w", pady=3)
        r += 1
        ttk.Checkbutton(adv, text="Permitir chamadas sem ZRTP",
                        variable=self.feat_zrtp_allow).grid(row=r, column=0, columnspan=2, sticky="w", pady=3)
        r += 1
        ttk.Label(
            adv,
            text=("ZRTP ativo no build: %s." % ("sim" if self.zrtp_available else "não"))
                 + (" Use o botão 🔒 na chamada para confirmar o SAS." if self.zrtp_available else
                    " Recompile o PJSIP com suporte a ZRTP para usar."),
            style="Muted.TLabel", wraplength=400, justify=tk.LEFT,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(0, 4))

        r += 1
        self._styled_button(adv, "💾  Salvar segurança/NAT", self._save_advanced, COLOR_SUCCESS).grid(
            row=r, column=0, columnspan=2, sticky="ew", pady=(8, 4))

        r += 1
        ttk.Label(
            adv, text="Alterações de transporte (TLS/STUN/TURN) só valem após reiniciar o app.",
            style="Muted.TLabel", wraplength=400, justify=tk.LEFT,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(0, 4))

    def _pick_file(self, entry):
        path = filedialog.askopenfilename(
            parent=self.adv_win,
            title="Selecionar arquivo",
            filetypes=[
                ("Todos os arquivos", "*.*"),
                ("Certificado/Chave", "*.pem *.crt *.cer *.key"),
            ],
        )
        if path:
            entry.delete(0, tk.END)
            entry.insert(0, path)

    def _save_advanced(self):
        if self.adv_win is None:
            return
        srtp_labels = {
            "Desabilitado": "disabled",
            "Opcional": "optional",
            "Obrigatório": "mandatory",
        }
        sec = {
            "tls": bool(self.adv_tls.get()),
            "tls_ca_file": self.adv_tls_ca.get().strip(),
            "tls_cert_file": self.adv_tls_cert.get().strip(),
            "tls_key_file": self.adv_tls_key.get().strip(),
            "srtp": srtp_labels.get(self.adv_srtp.get(), "disabled"),
            "srtp_tls_only": bool(self.adv_srtp_tls.get()),
        }
        turn_pw = self.adv_turn_password.get()
        if turn_pw:
            secrets.set("turn", turn_pw)
        nat = {
            "stun_server": self.adv_stun.get().strip(),
            "ice": bool(self.adv_ice.get()),
            "turn_enabled": bool(self.adv_turn_enabled.get()),
            "turn_server": self.adv_turn_server.get().strip(),
            "turn_user": self.adv_turn_user.get().strip(),
            "turn_password": secrets.get("turn", ""),
        }
        self.config_data["security"] = sec
        self.config_data["nat"] = nat
        # ZRTP foi movido da aba Recursos para cá.
        self.config_data["zrtp"] = {
            "enabled": bool(self.feat_zrtp_enabled.get()),
            "sas_required": bool(self.feat_zrtp_sas.get()),
            "allow_unencrypted": bool(self.feat_zrtp_allow.get()),
        }
        save_config(self.config_data)
        self.zrtp_config = _clean_zrtp(self.config_data["zrtp"])
        self.zrtp_enabled = self.zrtp_config["enabled"] and self.zrtp_available
        if self.zrtp_config["enabled"] and not self.zrtp_available:
            self.show_toast("ZRTP não está disponível neste build do PJSIP")
        messagebox.showinfo(
            "Segurança e NAT",
            "Configurações salvas.\n\nTLS, STUN, TURN e SRTP nas contas só terão efeito "
            "após reiniciar o aplicativo.",
            parent=self.adv_win,
        )

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
        self._codec_tree_selected = None
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
            tree.bind(
                "<<TreeviewSelect>>",
                lambda _event, selected_tree=tree: setattr(
                    self, "_codec_tree_selected", selected_tree
                ),
            )
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
        if self.endpoint is None:
            for tree in (self.audio_tree, self.video_tree):
                tree.delete(*tree.get_children())
            if hasattr(self, "codec_note") and self.codec_note is not None:
                self.codec_note.config(
                    text="Backend SIP indisponível neste sistema (pjsua2 é Linux-only neste build)."
                )
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
        if self.codec_win is None:
            return None
        tree = self._codec_tree_selected
        if tree is None or not tree.selection():
            if self.audio_tree.selection():
                tree = self.audio_tree
            elif self.video_tree.selection():
                tree = self.video_tree
        if tree is None:
            return None
        self._codec_tree_selected = tree
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
        kind = "video" if self._codec_tree_selected is self.video_tree else "audio"
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
        if self.endpoint is None:
            return
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
        if not self._sip_available:
            # Sem backend SIP (Win/Mac): mantém accounts vazio; UI mostra offline.
            self.accounts = []
            self.refresh()
            self.update_presence()
            return
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
                logging.error("Erro ao registrar %s@%s: %s", data["user"], data["server"], pj_error_text(e))
        self.refresh()
        self.update_presence()
        self._publish_presence()

    def register_account(self, data):
        user = data["user"]
        server = data["server"]

        acfg = pj.AccountConfig()
        acfg.idUri = f"sip:{user}@{server}"
        acfg.regConfig.registrarUri = f"sip:{server}"

        self._apply_security_config(acfg)
        self._apply_nat_config(acfg)
        self._apply_video_config(acfg)

        password = secrets.get(f"{user}@{server}", "")
        cred = pj.AuthCredInfo("digest", "*", user, 0, password)
        acfg.sipConfig.authCreds.append(cred)

        acc = MyAccount(self, data)
        acc.create(acfg)
        if not self.accounts:
            acc.setDefault()

        entry = {"acc": acc, "data": dict(data), "status": "REGISTERING", "buddies": []}
        self.accounts.append(entry)
        self._create_presence_buddies(entry)

    def _presence_uris_for_account(self, data):
        uris = set()
        for raw in self.config_data.get("presence_list") or []:
            uri = str(raw or "").strip()
            if uri:
                uris.add(uri if uri.lower().startswith("sip:") else f"sip:{uri}")
        for contact in self.contacts:
            if not contact.get("monitor_presence"):
                continue
            server = contact.get("server") or data.get("server", "")
            uri = build_sip_target(contact.get("number", ""), server)
            if uri:
                uris.add(uri)
        return sorted(uris)

    def _create_presence_buddies(self, entry):
        entry["buddies"] = []
        for uri in self._presence_uris_for_account(entry["data"]):
            try:
                entry["buddies"].append(MyBuddy(self, entry["acc"], uri))
                logging.info("Presença monitorada: %s", uri)
            except Exception as e:
                logging.warning("Não foi possível monitorar presença de %s: %s", uri, e)

    def _update_presence_ui(self):
        if self.contacts_win is not None:
            self._populate_contacts_tree()

    def _presence_uri_for_contact(self, contact):
        server = contact.get("server", "")
        if not server and self.accounts:
            server = self.accounts[0]["data"].get("server", "")
        return build_sip_target(contact.get("number", ""), server).lower()

    def _presence_label(self, contact):
        item = self._presence.get(self._presence_uri_for_contact(contact))
        if not item:
            return "—"
        status = item.get("status")
        if item.get("activity") == pj.PJRPID_ACTIVITY_BUSY:
            return item.get("text") or "Ocupado"
        if status == pj.PJSUA_BUDDY_STATUS_ONLINE:
            return "Online"
        if status == pj.PJSUA_BUDDY_STATUS_OFFLINE:
            return "Offline"
        text = item.get("text") or ""
        return text or "Desconhecido"

    def _publish_presence(self):
        if not self.publish_presence:
            return
        if self.call_state in ("IN_CALL", "HOLD"):
            text = "Em chamada"
            activity = pj.PJRPID_ACTIVITY_BUSY
        elif self.call_state in ("CALLING", "RINGING", "INCOMING"):
            text = "Chamando"
            activity = pj.PJRPID_ACTIVITY_BUSY
        else:
            text = "Disponível"
            activity = pj.PJRPID_ACTIVITY_UNKNOWN
        for entry in self.accounts:
            if entry.get("status") != "ONLINE":
                continue
            try:
                presence = pj.PresenceStatus()
                presence.status = pj.PJSUA_BUDDY_STATUS_ONLINE
                presence.statusText = text
                presence.activity = activity
                entry["acc"].setOnlineStatus(presence)
            except Exception as e:
                logging.warning("Não foi possível publicar presença: %s", e)

    def _apply_security_config(self, acfg):
        sec = self.config_data.get("security") or {}
        if self._tls_tid is not None:
            try:
                acfg.sipConfig.transportId = self._tls_tid
            except Exception as e:
                logging.warning("Não foi possível usar o transporte TLS na conta: %s", e)

        srtp = str(sec.get("srtp") or "disabled")
        if srtp != "disabled":
            try:
                if srtp == "mandatory":
                    acfg.mediaConfig.srtpUse = pj.PJMEDIA_SRTP_MANDATORY
                else:
                    acfg.mediaConfig.srtpUse = pj.PJMEDIA_SRTP_OPTIONAL
                # Sem isso o pjsua2 assume srtpSecureSignaling=1 ("SRTP exige
                # transporte seguro, ex.: TLS"). Como a conta normalmente usa
                # UDP, qualquer chamada falhava de imediato com
                # PJSIP_ESESSIONINSECURE ("Require secure session/transport").
                if sec.get("srtp_tls_only"):
                    try:
                        acfg.mediaConfig.srtpSecureSignaling = pj.PJMEDIA_SRTP_USE_SRTP
                    except AttributeError:
                        acfg.mediaConfig.srtpSecureSignaling = 1  # PJMEDIA_SRTP_USE_SRTP
                else:
                    acfg.mediaConfig.srtpSecureSignaling = 0  # PJMEDIA_SRTP_NO_SIGNALING_SECURE
            except Exception as e:
                logging.warning("Não foi possível aplicar SRTP na conta: %s", pj_error_text(e))

        if self.zrtp_enabled:
            try:
                acfg.mediaConfig.zrtpEnabled = True
                acfg.mediaConfig.zrtpSasRequired = self.zrtp_config["sas_required"]
                acfg.mediaConfig.zrtpAllowUnencrypted = self.zrtp_config["allow_unencrypted"]
                logging.info("ZRTP habilitado para %s", acfg.idUri)
            except AttributeError:
                self.zrtp_available = False
                self.zrtp_enabled = False
                logging.warning("ZRTP não está disponível neste build do PJSIP")

    def _apply_nat_config(self, acfg):
        nat = self.config_data.get("nat") or {}
        try:
            acfg.natConfig.iceEnabled = bool(nat.get("ice"))
        except Exception as e:
            logging.warning("Não foi possível ativar ICE: %s", e)

        if nat.get("turn_enabled") and str(nat.get("turn_server") or ""):
            try:
                acfg.natConfig.turnEnabled = True
                acfg.natConfig.turnServer = str(nat.get("turn_server"))
                acfg.natConfig.turnUserName = str(nat.get("turn_user") or "")
                acfg.natConfig.turnPassword = str(nat.get("turn_password") or "")
                try:
                    acfg.natConfig.turnConnType = pj.PJ_TURN_TP_UDP
                except Exception:
                    pass
            except Exception as e:
                logging.warning("Não foi possível aplicar TURN: %s", e)

    def _apply_video_config(self, acfg):
        try:
            vcfg = acfg.videoConfig
            vcfg.autoShowIncoming = True
            vcfg.autoTransmitOutgoing = True
            vid = (self.config_data.get("video") or {}).get("device", -1)
            if isinstance(vid, int) and vid >= 0:
                vcfg.defaultCaptureDevice = vid
        except Exception as e:
            logging.warning("Não foi possível aplicar configuração de vídeo: %s", e)

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
        win.geometry("480x480")
        win.minsize(440, 430)
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

            forward_frame = ttk.LabelFrame(container, text="Encaminhamento")
            forward_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 6))
            forward_frame.grid_columnconfigure(1, weight=1)
            forward_fields = (
                ("Incondicional", "forward_unconditional"),
                ("Ocupado", "forward_busy"),
                ("Sem resposta", "forward_no_answer"),
            )
            for fr, (label, key) in enumerate(forward_fields):
                ttk.Label(forward_frame, text=label).grid(
                    row=fr, column=0, sticky="w", padx=(0, 8), pady=3
                )
                entry_widget = ttk.Entry(forward_frame)
                entry_widget.insert(0, entry["data"].get(key, ""))
                entry_widget.grid(row=fr, column=1, sticky="ew", pady=3)
                setattr(self, f"edit_{key}", entry_widget)

            ttk.Label(forward_frame, text="Tempo sem resposta (s)").grid(
                row=3, column=0, sticky="w", padx=(0, 8), pady=3
            )
            self.edit_forward_no_answer_timeout = ttk.Spinbox(
                forward_frame, from_=5, to=60, width=8
            )
            self.edit_forward_no_answer_timeout.set(
                str(entry["data"].get("forward_no_answer_timeout", 20))
            )
            self.edit_forward_no_answer_timeout.grid(row=3, column=1, sticky="w", pady=3)

            self._styled_button(
                container, "💾  Salvar alterações", self.save_edit_account, COLOR_SUCCESS
            ).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 4))

            self._styled_button(container, "Fechar", win.destroy, COLOR_PRIMARY).grid(
                row=5, column=0, columnspan=2, sticky="ew"
            )

            self.root.update_idletasks()
            self._grab_modal(win)
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

        try:
            forward_timeout = int(self.edit_forward_no_answer_timeout.get())
        except (TypeError, ValueError):
            forward_timeout = 20
        forward_data = {
            "forward_unconditional": self.edit_forward_unconditional.get().strip(),
            "forward_busy": self.edit_forward_busy.get().strip(),
            "forward_no_answer": self.edit_forward_no_answer.get().strip(),
            "forward_no_answer_timeout": max(5, min(60, forward_timeout)),
        }

        for i, acc_cfg in enumerate(self.config_data["accounts"]):
            if _account_key(acc_cfg) == old_key:
                self.config_data["accounts"][i] = {
                    "user": user,
                    "server": server,
                    **forward_data,
                }
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

    def export_data(self):
        data = {
            "version": 1,
            "accounts": [
                {"user": a["user"], "server": a["server"]}
                for a in self.config_data.get("accounts", [])
            ],
            "contacts": self.contacts,
        }
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Exportar dados",
            defaultextension=".json",
            initialfile="voiceneves_backup.json",
            filetypes=[("Arquivo JSON", "*.json"), ("Todos os arquivos", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logging.info("Dados exportados para %s", path)
            messagebox.showinfo("Exportar", f"Dados exportados para:\n{path}")
        except OSError as e:
            logging.error("Falha ao exportar dados: %s", e)
            messagebox.showerror("Exportar", f"Falha ao exportar:\n{e}")

    def import_data(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Importar dados",
            filetypes=[("Arquivo JSON", "*.json"), ("Todos os arquivos", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logging.error("Falha ao ler arquivo de importação: %s", e)
            messagebox.showerror("Importar", f"Falha ao ler o arquivo:\n{e}")
            return
        if not isinstance(data, dict):
            messagebox.showerror("Importar", "Formato inválido.")
            return

        added_acc = 0
        existing_keys = {_account_key(a) for a in self.config_data.get("accounts", [])}
        for item in data.get("accounts") or []:
            if not isinstance(item, dict):
                continue
            user = clean_extension(item.get("user", ""))
            server = str(item.get("server", "") or "").strip()
            if not is_valid_extension(user) or not is_valid_server(server):
                continue
            key = f"{user}@{server}"
            if key in existing_keys:
                continue
            self.config_data.setdefault("accounts", []).append({"user": user, "server": server})
            existing_keys.add(key)
            added_acc += 1

        added_ct = 0
        existing_ct = {
            (clean_extension(c.get("number", "")), c.get("name", "")) for c in self.contacts
        }
        for c in data.get("contacts") or []:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "").strip()
            number = clean_extension(c.get("number", ""))
            if not name or not number:
                continue
            if (number, name) in existing_ct:
                continue
            self.contacts.append(
                {
                    "name": name,
                    "number": number,
                    "server": str(c.get("server") or "").strip(),
                    "favorite": bool(c.get("favorite")),
                    "ringtone": str(c.get("ringtone") or "").strip(),
                    "monitor_presence": bool(c.get("monitor_presence")),
                }
            )
            existing_ct.add((number, name))
            added_ct += 1

        if added_acc or added_ct:
            save_config(self.config_data)
            self.contacts_store.save(self.contacts)
            self.refresh_favorites()
            if added_acc and self.call_state == "IDLE":
                self.auto_register_accounts()
            if self.contacts_win is not None:
                self._filter_contacts()
        logging.info("Importados %d conta(s) e %d contato(s)", added_acc, added_ct)
        messagebox.showinfo(
            "Importar",
            f"Importação concluída:\n{added_acc} conta(s) e {added_ct} contato(s) adicionados.\n\n"
            "As senhas das contas não são importadas (ficam no cofre de senhas do sistema).",
        )

    def update_account_status(self, acc, status):
        changed = None
        for entry in self.accounts:
            if entry["acc"] == acc:
                if entry["status"] != status and status in ("ONLINE", "OFFLINE"):
                    changed = (entry["data"], status)
                entry["status"] = status
                break
        self.refresh()
        self.update_presence()
        if changed:
            data, st = changed
            ident = f"{data['user']}@{data['server']}"
            if st == "ONLINE":
                notify_send("Registro SIP", f"{ident} online", "low")
                self.show_toast(f"Conta {ident} conectada")
            else:
                notify_send("Registro SIP", f"{ident} offline", "normal")
                self.show_toast(f"Conta {ident} offline")

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
                f"{icon}  {entry['data']['user']}  ({label})",
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
    def record_call(self, label, call=None):
        call = call if call is not None else self.current_call
        kind = ""
        if label.startswith("Saída para "):
            kind = "outgoing"
        elif label.startswith("Entrada de "):
            kind = "incoming"
        elif label.startswith("Transferência"):
            kind = "transfer"
        elif label.startswith("Conferência"):
            kind = "conference"
        elif label.startswith("Gravação de "):
            kind = "recording"
        self.history.append(
            {
                "ts": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "label": label,
                "kind": kind,
                "status": "",
                "duration": "",
                "secure": False,
            }
        )
        if len(self.history) > 500:
            self.history = self.history[-500:]
        save_history(self.history)
        if call is not None:
            try:
                call._history_idx = len(self.history) - 1
                call._history_kind = kind
            except Exception:
                pass

    def show_history(self):
        win = tk.Toplevel(self.root)
        win.title("Histórico de Chamadas")
        win.geometry("540x420")
        win.minsize(480, 320)
        win.transient(self.root)
        self._grab_modal(win)
        self.history_win = win
        win.protocol("WM_DELETE_WINDOW", lambda: (win.destroy(), setattr(self, "history_win", None)))

        container = ttk.Frame(win, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        columns = ("data", "tipo", "status", "numero", "duracao", "segura")
        tree = ttk.Treeview(container, columns=columns, show="headings", selectmode="browse")
        tree.heading("data", text="Data/Hora")
        tree.heading("tipo", text="Tipo")
        tree.heading("status", text="Status")
        tree.heading("numero", text="Número/Contato")
        tree.heading("duracao", text="Duração")
        tree.heading("segura", text="Segura")
        tree.column("data", width=118, anchor="w")
        tree.column("tipo", width=100, anchor="center")
        tree.column("status", width=110, anchor="center")
        tree.column("numero", width=220, anchor="w")
        tree.column("duracao", width=70, anchor="center")
        tree.column("segura", width=65, anchor="center")
        tree.grid(row=0, column=0, sticky="nsew")
        tree.bind("<Double-1>", lambda e: self._call_history_number(tree))
        tree.bind("<Return>", lambda e: self._call_history_number(tree))

        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)
        self.history_tree = tree

        for entry in reversed(self.history):
            tipo, numero = self._history_split(entry)
            tree.insert(
                "",
                tk.END,
                values=(
                    entry.get("ts", ""),
                    tipo,
                    entry.get("status") or "—",
                    numero,
                    entry.get("duration") or "—",
                    "🔒" if entry.get("secure") else "—",
                ),
            )

        btn_frame = tk.Frame(container, bg=COLOR_BG)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        btn_frame.grid_columnconfigure(0, weight=1)
        self._styled_button(
            btn_frame, "🗑  Limpar", lambda: self._clear_history_ui(tree, win), COLOR_DANGER
        ).grid(row=0, column=0, sticky="w")
        self._styled_button(
            btn_frame, "Fechar",
            lambda: (win.destroy(), setattr(self, "history_win", None)), COLOR_PRIMARY
        ).grid(row=0, column=2, sticky="e", padx=(4, 0))
        self._styled_button(
            btn_frame, "Ligar", lambda: self._call_history_number(tree), COLOR_SUCCESS
        ).grid(row=0, column=1, sticky="e", padx=(4, 0))

    @staticmethod
    def _history_split(entry):
        """Extrai tipo e número/contato de um item de histórico (antigo ou novo)."""
        label = entry.get("label", "") if isinstance(entry, dict) else str(entry)
        kind = entry.get("kind", "") if isinstance(entry, dict) else ""
        tipo = {
            "outgoing": "Saída",
            "incoming": "Entrada",
            "transfer": "Transferência",
            "conference": "Conferência",
            "recording": "Gravação",
        }.get(kind)
        if kind == "incoming" and entry.get("status") == "Perdida":
            tipo = "Perdida"
        if not tipo:
            if label.startswith("Saída para "):
                tipo = "Saída"
            elif label.startswith("Entrada de "):
                tipo = "Entrada"
            elif label.startswith("Transferência"):
                tipo = "Transferência"
            elif label.startswith("Conferência"):
                tipo = "Conferência"
            elif label.startswith("Gravação de "):
                tipo = "Gravação"
            else:
                tipo = "—"
        for prefix in (
            "Saída para ",
            "Entrada de ",
            "Transferência cega para ",
            "Transferência assistida para ",
            "Transferência assistida concluída para ",
            "Gravação de ",
        ):
            if label.startswith(prefix):
                return tipo, label[len(prefix):]
        return tipo, label

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

    # =========================
    # CONTATOS / DIRETÓRIO
    # =========================
    def _dialable_from_uri(self, raw):
        """Extrai um ramal discável de um URI SIP (ex.: sip:3000@host;transport=udp)."""
        s = str(raw or "")
        if s.lower().startswith("sip:"):
            s = s[4:]
        s = s.split(";", 1)[0]
        if "@" in s:
            s = s.rsplit("@", 1)[0]
        return clean_extension(s)

    def _find_contact_by_number(self, uri):
        num = self._dialable_from_uri(uri)
        if not num:
            return None
        for c in self.contacts:
            if clean_extension(c.get("number", "")) == num:
                return c
        return None

    def refresh_favorites(self):
        """Reconstrói os botões de discagem rápida (favoritos) sob o teclado."""
        frame = getattr(self, "favorites_frame", None)
        if frame is None:
            return
        for w in frame.winfo_children():
            w.destroy()
        favs = [c for c in self.contacts if c.get("favorite")][:4]
        if not favs:
            ttk.Label(
                frame,
                text="⭐ Favoritos: marque contatos para discagem rápida",
                style="Muted.TLabel",
            ).pack(side=tk.LEFT, padx=4)
        else:
            for c in favs:
                label = c["name"] if len(c["name"]) <= 14 else c["name"][:13] + "…"
                btn = self._styled_button(
                    frame, f"⭐ {label}", lambda ct=c: self.call_contact(ct),
                    COLOR_WARNING, fg=COLOR_TEXT, pady=4, font=(self._font, 9),
                )
                btn.pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
                ToolTip(btn, f"Ligar para {c['name']} ({c['number']})")
        btn = self._styled_button(
            frame, "📒 Contatos", self.open_contacts, COLOR_PRIMARY,
            fg="#FFFFFF", pady=3, font=(self._font, 10),
        )
        btn.pack(side=tk.LEFT, padx=2)
        ToolTip(btn, "Abrir diretório de contatos")

    def call_contact(self, contact):
        if not contact:
            return
        number = clean_extension(contact.get("number", ""))
        if not number:
            messagebox.showwarning("Contato", "Este contato não possui um ramal/número válido.")
            return
        self.number.delete(0, tk.END)
        self.number.insert(0, number)
        server = contact.get("server") or None
        self._close_contacts_win()
        self.make_call(number, server)

    def _grab_modal(self, win, _tries=0):
        """Torna a janela modal de forma segura.

        No Wayland/XWayland, grab_set() lança "grab failed: window not
        viewable" se chamado antes da janela estar mapeada -- o que abortava
        open_contacts() e deixava a janela em branco. Aqui tentamos em loop
        não-bloqueante (via after) até a janela ficar visível, no máximo ~1s.
        """
        try:
            win.grab_set()
        except tk.TclError:
            if _tries < 20:
                try:
                    win.after(50, lambda: self._grab_modal(win, _tries + 1))
                except tk.TclError:
                    pass

    def _raise_window(self, win, _tries=0):
        """Garante que a janela apareça acima da que a chamou.

        Em alguns gerenciadores de janela o Toplevel nasce atrás do pai
        (especialmente quando o clique veio de outra Toplevel); elevamos
        e damos foco imediatamente e repetimos por ~0,8s até confirmar.
        """
        if win is None or not win.winfo_exists():
            return
        try:
            win.deiconify()
            win.lift()
            win.focus_force()
        except tk.TclError:
            return
        if _tries < 8 and (
            not win.winfo_viewable() or self.root.winfo_containing(1, 1) is None
        ):
            try:
                win.after(
                    100,
                    lambda: self._raise_window(win, _tries + 1),
                )
            except tk.TclError:
                pass

    def open_contacts(self):
        if self.contacts_win is not None:
            try:
                self.contacts_win.deiconify()
                self.contacts_win.lift()
            except tk.TclError:
                self.contacts_win = None
        if self.contacts_win is not None:
            return
        win = tk.Toplevel(self.root)
        win.title("Contatos / Diretório")
        win.geometry("580x480")
        win.minsize(520, 380)
        win.transient(self.root)
        self._grab_modal(win)
        self.contacts_win = win
        win.protocol("WM_DELETE_WINDOW", self._close_contacts_win)

        container = ttk.Frame(win, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(1, weight=1)

        search_frame = ttk.Frame(container)
        search_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        search_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(search_frame, text="Buscar:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.contact_search = ttk.Entry(search_frame)
        self.contact_search.grid(row=0, column=1, sticky="ew")
        self.contact_search.bind("<KeyRelease>", self._filter_contacts)
        ToolTip(self.contact_search, "Filtra por nome, ramal ou servidor (em tempo real)")
        self.contact_search.focus_set()

        columns = ("fav", "nome", "numero", "servidor", "status", "toque")
        tree = ttk.Treeview(container, columns=columns, show="headings", selectmode="browse", height=14)
        tree.heading("fav", text="★")
        tree.heading("nome", text="Nome")
        tree.heading("numero", text="Ramal/Número")
        tree.heading("servidor", text="Servidor")
        tree.heading("status", text="Presença")
        tree.heading("toque", text="Toque")
        tree.column("fav", width=40, anchor="center")
        tree.column("nome", width=180, anchor="w")
        tree.column("numero", width=120, anchor="w")
        tree.column("servidor", width=150, anchor="w")
        tree.column("status", width=90, anchor="center")
        tree.column("toque", width=110, anchor="w")
        tree.grid(row=1, column=0, sticky="nsew")
        tree.bind("<Double-1>", lambda e: self._call_selected_contact(tree))
        tree.bind("<Return>", lambda e: self._call_selected_contact(tree))
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)
        self.contact_tree = tree

        btn_frame = tk.Frame(container, bg=COLOR_BG)
        btn_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        btn_frame.grid_columnconfigure(0, weight=1)

        left = tk.Frame(btn_frame, bg=COLOR_BG)
        left.pack(side=tk.LEFT)
        right = tk.Frame(btn_frame, bg=COLOR_BG)
        right.pack(side=tk.RIGHT)

        self._styled_button(left, "➕  Novo", lambda: self.edit_contact(None), COLOR_SUCCESS).pack(side=tk.LEFT, padx=2)
        self._styled_button(
            left, "✏️  Editar", lambda: self.edit_contact(self._selected_contact(tree)),
            COLOR_WARNING, fg=COLOR_TEXT,
        ).pack(side=tk.LEFT, padx=2)
        self._styled_button(
            left, "🗑  Excluir", lambda: self.delete_contact(self._selected_contact(tree)),
            COLOR_DANGER,
        ).pack(side=tk.LEFT, padx=2)
        self._styled_button(
            right, "Ligar", lambda: self._call_selected_contact(tree), COLOR_SUCCESS
        ).pack(side=tk.LEFT, padx=2)
        self._styled_button(
            right, "Fechar", self._close_contacts_win, COLOR_PRIMARY
        ).pack(side=tk.LEFT, padx=2)

        self._filtered_contacts = self._directory_contacts()
        self._populate_contacts_tree()

    def _close_contacts_win(self):
        if self.contact_edit_win is not None:
            try:
                self.contact_edit_win.destroy()
            except Exception:
                pass
            self.contact_edit_win = None
        if self.contacts_win is not None:
            try:
                self.contacts_win.destroy()
            except Exception:
                pass
            self.contacts_win = None
        self.contact_search = None
        self.contact_tree = None
        self._filtered_contacts = []

    def _selected_contact(self, tree):
        sel = tree.selection()
        if not sel:
            return None
        try:
            idx = int(tree.item(sel[0], "text"))
        except (ValueError, TypeError):
            return None
        if 0 <= idx < len(self._filtered_contacts):
            return self._filtered_contacts[idx]
        return None

    def _populate_contacts_tree(self):
        tree = getattr(self, "contact_tree", None)
        if tree is None:
            return
        for item in tree.get_children():
            tree.delete(item)
        for i, c in enumerate(self._filtered_contacts):
            ring = c.get("ringtone") or ""
            tree.insert(
                "", tk.END, text=str(i),
                values=(
                    "🏢" if c.get("is_ldap") else ("★" if c.get("favorite") else " "),
                    c.get("name", ""),
                    c.get("number", ""),
                    c.get("server", "") or "—",
                    self._presence_label(c),
                    os.path.basename(ring) if ring else "padrão",
                ),
            )

    def _filter_contacts(self, _event=None):
        q = (self.contact_search.get() if self.contact_search is not None else "").strip()
        self._filtered_contacts = self._directory_contacts(q)
        self._populate_contacts_tree()

    def _directory_contacts(self, query=""):
        q = str(query or "").strip().lower()
        local = [
            c for c in self.contacts
            if not q or q in f"{c.get('name', '')} {c.get('number', '')} {c.get('server', '')}".lower()
        ]
        remote = self.ldap_manager.search(q) if self.ldap_manager is not None else []
        merged = list(local)
        seen = {(c.get("name", "").lower(), c.get("number", "")) for c in local}
        for contact in remote:
            key = (contact.get("name", "").lower(), contact.get("number", ""))
            if key not in seen:
                merged.append(contact)
                seen.add(key)
        return merged

    def _call_selected_contact(self, tree):
        contact = self._selected_contact(tree)
        if contact is None:
            messagebox.showinfo("Contatos", "Selecione um contato na lista.", parent=self.contacts_win)
            return
        self.call_contact(contact)

    def edit_contact(self, contact=None):
        editing = contact is not None
        win = tk.Toplevel(self.root)
        win.title("Editar Contato" if editing else "Novo Contato")
        win.geometry("460x330")
        win.transient(self.root)
        self._grab_modal(win)
        self._raise_window(win)
        self.contact_edit_win = win
        win.protocol(
            "WM_DELETE_WINDOW",
            lambda: (win.destroy(), setattr(self, "contact_edit_win", None)),
        )

        container = ttk.Frame(win, padding=12)
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_columnconfigure(1, weight=1)

        values = {
            "name": tk.StringVar(value=contact["name"] if editing else ""),
            "number": tk.StringVar(value=contact["number"] if editing else ""),
            "server": tk.StringVar(value=contact.get("server", "") if editing else ""),
            "favorite": tk.BooleanVar(value=bool(contact.get("favorite")) if editing else False),
            "ringtone": tk.StringVar(value=contact.get("ringtone", "") if editing else ""),
            "monitor_presence": tk.BooleanVar(
                value=bool(contact.get("monitor_presence")) if editing else False
            ),
        }

        r = 0
        ttk.Label(container, text="Nome *").grid(row=r, column=0, sticky="w", padx=(0, 8), pady=4)
        e_name = ttk.Entry(container, textvariable=values["name"])
        e_name.grid(row=r, column=1, sticky="ew", pady=4)

        r += 1
        ttk.Label(container, text="Ramal/Número *").grid(row=r, column=0, sticky="w", padx=(0, 8), pady=4)
        e_number = ttk.Entry(container, textvariable=values["number"])
        e_number.grid(row=r, column=1, sticky="ew", pady=4)

        r += 1
        ttk.Label(container, text="Servidor (opcional)").grid(row=r, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(container, textvariable=values["server"]).grid(row=r, column=1, sticky="ew", pady=4)

        r += 1
        ttk.Checkbutton(
            container, text="⭐ Favorito (discagem rápida no teclado)",
            variable=values["favorite"],
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=4)

        r += 1
        ttk.Checkbutton(
            container, text="Monitorar presença deste contato",
            variable=values["monitor_presence"],
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=4)

        r += 1
        ttk.Label(container, text="Toque (opcional)").grid(row=r, column=0, sticky="w", padx=(0, 8), pady=4)
        ring_row = tk.Frame(container, bg=COLOR_BG)
        ring_row.grid(row=r, column=1, sticky="ew", pady=4)
        ring_row.grid_columnconfigure(0, weight=1)
        ttk.Entry(ring_row, textvariable=values["ringtone"]).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._styled_button(
            ring_row, "…", lambda: values["ringtone"].set(self._pick_ringtone_path(values["ringtone"].get())),
            COLOR_MUTED,
        ).grid(row=0, column=1, padx=(0, 2))
        self._styled_button(ring_row, "✕", lambda: values["ringtone"].set(""), COLOR_MUTED).grid(row=0, column=2)

        r += 1
        btn_row = tk.Frame(container, bg=COLOR_BG)
        btn_row.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        btn_row.grid_columnconfigure(0, weight=1)
        self._styled_button(
            btn_row, "💾  Salvar", lambda: self._save_contact(contact, values, win), COLOR_SUCCESS
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._styled_button(
            btn_row, "Cancelar", lambda: (win.destroy(), setattr(self, "contact_edit_win", None)), COLOR_PRIMARY
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        e_name.focus_set()
        e_name.bind("<Return>", lambda ev: e_number.focus_set())
        e_number.bind("<Return>", lambda ev: self._save_contact(contact, values, win))

    def _pick_ringtone_path(self, current):
        path = filedialog.askopenfilename(
            parent=self.contact_edit_win,
            title="Escolher toque de chamada (WAV)",
            filetypes=[("Áudio WAV", "*.wav"), ("Todos os arquivos", "*.*")],
        )
        return path or current

    def _save_contact(self, old, values, win):
        name = values["name"].get().strip()
        number = clean_extension(values["number"].get().strip())
        server_raw = values["server"].get().strip()
        if not name:
            messagebox.showwarning("Contato", "Informe o nome do contato.", parent=win)
            return
        if not number:
            messagebox.showwarning("Contato", "Informe o ramal/número do contato.", parent=win)
            return
        if server_raw and not is_valid_server(server_raw):
            messagebox.showwarning("Contato", "Servidor inválido.", parent=win)
            return
        contact = {
            "name": name,
            "number": number,
            "server": server_raw,
            "favorite": bool(values["favorite"].get()),
            "ringtone": values["ringtone"].get().strip(),
            "monitor_presence": bool(values["monitor_presence"].get()),
        }
        presence_changed = bool(old and old.get("monitor_presence")) != contact["monitor_presence"]
        if old is not None and old in self.contacts:
            self.contacts[self.contacts.index(old)] = contact
        else:
            self.contacts.append(contact)
        self.contacts_store.save(self.contacts)
        self.refresh_favorites()
        if presence_changed and self.call_state == "IDLE":
            self.auto_register_accounts()
        if self.contacts_win is not None:
            self._filter_contacts()
        try:
            win.destroy()
        except tk.TclError:
            pass
        self.contact_edit_win = None

    def delete_contact(self, contact=None):
        if contact is None:
            messagebox.showinfo("Contatos", "Selecione um contato na lista.", parent=self.contacts_win)
            return
        if not messagebox.askyesno(
            "Excluir Contato", f"Excluir o contato '{contact['name']}'?", parent=self.contacts_win
        ):
            return
        if contact in self.contacts:
            self.contacts.remove(contact)
            self.contacts_store.save(self.contacts)
        self.refresh_favorites()
        if self.contacts_win is not None:
            self._filter_contacts()

    def _history_selected_number(self):
        tree = getattr(self, "history_tree", None)
        if tree is None:
            return None
        sel = tree.selection()
        if not sel:
            return None
        values = tree.item(sel[0], "values")
        if len(values) >= 4:
            num = values[3]
            return num if num and num != "—" else None
        return None

    def _call_history_number(self, tree=None):
        num = self._history_selected_number()
        if num is None:
            messagebox.showinfo("Histórico", "Selecione uma chamada com número para ligar.")
            return
        self._close_history_win()
        number = self._dialable_from_uri(num)
        if not number:
            return
        self.number.delete(0, tk.END)
        self.number.insert(0, number)
        self.make_call(number, None)

    def _close_history_win(self):
        win = getattr(self, "history_win", None)
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
            self.history_win = None

    def make_call(self, number=None, server=None):
        if not self._sip_available:
            messagebox.showinfo(
                "Backend SIP indisponível",
                "pjsua2 não está disponível neste sistema (este build só suporta "
                "chamadas SIP no Linux, com G.729/BCG729 embutido).\n\n"
                "Para Linux: instale/compile o pjsua2. Para Win/Mac: um backend "
                "pjsua2 cross-compiled ou um alternativo (linphone-sdk) é necessário.",
            )
            return
        entry = self.selected_account()
        if server:
            for a in self.accounts:
                if a["data"].get("server", "").lower() == server.lower():
                    entry = a
                    break
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

        number = clean_extension(number if number is not None else self.number.get())
        if not number:
            messagebox.showwarning("Número inválido", "Informe um número para ligar.")
            return

        self._last_number = number

        dest = f"sip:{number}@{entry['data']['server']}"
        logging.info("Ligando para %s usando a conta %s", dest, entry["data"]["user"])

        try:
            if self.current_call is not None and self.current_call is not self.incoming_call:
                self._disconnect_call_media()
                if self._call_is_confirmed(self.current_call):
                    self._hold_call(self.current_call)

            self.muted = False
            self.current_call = MyCall(entry["acc"], self)
            op = pj.CallOpParam(False)
            op.opt.audioCount = 1
            op.opt.videoCount = 1 if (self.video_enabled and self._has_video) else 0
            self._apply_video_call_options(op)
            self.current_call.makeCall(dest, op)
            self._track_call(self.current_call)
            self.held_calls.discard(self.current_call.getId())
            self.set_call_state("CALLING")
            self._start_ringback()
            self.record_call(f"Saída para {number}")
            self.update_call_ui()
        except Exception as e:
            self.current_call = None
            logging.error("Erro ao ligar: %s", pj_error_text(e))
            msg = f"Falha ao ligar: {pj_error_text(e)}"
            if is_audio_device_error(e):
                msg += "\n\n" + audio_error_hint()
            messagebox.showerror("Erro", msg)

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
        self.record_call(f"Entrada de {remote}", call=call)
        contact = self._find_contact_by_number(remote)
        self._contact_ringtone = (contact.get("ringtone") or "") if contact else ""
        caller = contact["name"] if contact else self._dialable_from_uri(remote)
        notify_send("Chamada recebida", caller or "Número desconhecido", "critical")
        self.update_call_ui()
        if self.auto_answer:
            self.root.after(1000, self._auto_answer_if_ringing, call)

    def _auto_answer_if_ringing(self, call):
        if self.auto_answer and self.call_state == "INCOMING" and self.incoming_call is call:
            logging.info("Auto-atendendo chamada recebida")
            self.answer()

    def _redirect_incoming_call(self, call, target_uri, reason):
        """Responde uma chamada INVITE com 302 e destino Contact."""
        try:
            if reason in ("incondicional", "ocupado"):
                self._ui(self._record_forwarded_incoming, call)
            op = pj.CallOpParam(False)
            op.statusCode = 302
            header = pj.SipHeader()
            header.hName = "Contact"
            header.hValue = f"<{target_uri}>"
            op.txOption.headers.push_back(header)
            call._forwarded = True
            call._forward_reason = reason
            call._forward_target = target_uri
            call.answer(op)
        except Exception as e:
            logging.error("Falha no encaminhamento %s para %s: %s", reason, target_uri, pj_error_text(e))

    def _record_forwarded_incoming(self, call):
        try:
            remote = call.getInfo().remoteUri
        except Exception:
            remote = "desconhecido"
        self.history.append(
            {
                "ts": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "label": f"Entrada de {remote}",
                "kind": "incoming",
                "status": "",
                "duration": "",
                "secure": False,
            }
        )
        if len(self.history) > 500:
            self.history = self.history[-500:]
        save_history(self.history)
        try:
            call._history_idx = len(self.history) - 1
            call._history_kind = "incoming"
        except Exception:
            pass

    def _schedule_forward_no_answer(self, call, target_uri, timeout):
        try:
            call_id = call.getId()
        except Exception:
            return
        old_timer = self._forward_timers.pop(call_id, None)
        if old_timer is not None:
            try:
                self.root.after_cancel(old_timer)
            except Exception:
                pass
        self._forward_timers[call_id] = self.root.after(
            timeout * 1000, self._forward_no_answer_timeout, call, target_uri
        )

    def _forward_no_answer_timeout(self, call, target_uri):
        try:
            call_id = call.getId()
        except Exception:
            return
        self._forward_timers.pop(call_id, None)
        if self.incoming_call is not call or call_id not in self.calls:
            return
        logging.info("Encaminhamento sem resposta para %s", target_uri)
        call._forwarded = True
        call._forward_reason = "sem resposta"
        call._forward_target = target_uri
        self._redirect_incoming_call(call, target_uri, "sem resposta")
        self.show_toast(f"Chamada encaminhada para {target_uri}")
        self.incoming_call = None
        self.current_call = None
        self._stop_ringtone()
        self.set_call_state("IDLE")
        self.update_call_ui()

    def answer(self):
        if self.current_call is None:
            return
        try:
            try:
                call_id = self.current_call.getId()
                timer_id = self._forward_timers.pop(call_id, None)
                if timer_id is not None:
                    self.root.after_cancel(timer_id)
            except Exception:
                pass
            op = pj.CallOpParam(False)
            op.statusCode = 200
            op.opt.audioCount = 1
            op.opt.videoCount = 1 if (self.video_enabled and self._has_video) else 0
            self._apply_video_call_options(op)
            self.current_call.answer(op)
            self.incoming_call = None
            self.set_call_state("CALLING")
            self.update_call_ui()
        except Exception as e:
            logging.error("Erro ao atender: %s", pj_error_text(e))
            msg = f"Falha ao atender: {pj_error_text(e)}"
            if is_audio_device_error(e):
                msg += "\n\n" + audio_error_hint()
            messagebox.showerror("Erro", msg)

    def hangup(self):
        if self.recording:
            self._stop_recording()
        call = self.current_call
        self.current_call = None
        self.incoming_call = None
        self.current_audio_media = None
        self.muted = False
        self.btn_mute.config(text="Mute")
        self._teardown_video_ui()

        if call is not None:
            try:
                call._user_hangup = True
                call.hangup(pj.CallOpParam())
            except Exception as e:
                logging.error("Erro ao desligar: %s", pj_error_text(e))

        self._stop_ringback(reason="desligar")
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
            self._call_started.setdefault(call.getId(), time.time())
            # Só cessa o ringback se QUEM confirmou é a chamada tocando;
            # o CONFIRMED da perna em espera (re-INVITE do hold) não deve
            # matar o toque da chamada nova.
            if call is self.current_call:
                self._stop_ringback(reason="chamada atual confirmada")
            if self._pending_xfer is not None and self._pending_xfer.get("dst") is call:
                self._complete_attended_xfer(call)
            elif self.conf_active:
                self._add_leg_to_conference(call)
                for cid in list(self.conf_media):
                    c = self.calls.get(cid)
                    if (
                        c is not None
                        and cid != call.getId()
                        and cid in self.held_calls
                    ):
                        self._unhold_call(c)
                if call is self.current_call:
                    self.set_call_state("IN_CALL")
            elif call is self.current_call:
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
        self._stop_moh(call)
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
            self._start_moh(call)
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
            self._stop_moh(call)
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
        if self.recording:
            self._stop_recording()
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
            # Reativa o toque se ele foi parado por um evento alheio (ex.:
            # queda da perna em espera) enquanto esta chamada ainda toca.
            if not self._call_is_confirmed(call):
                self._start_ringback()
            self.set_call_state("RINGING")
        self.update_call_ui()

    def _after_call_ended(self, call):
        try:
            call_id = call.getId()
            timer_id = self._forward_timers.pop(call_id, None)
            if timer_id is not None:
                self.root.after_cancel(timer_id)
        except Exception:
            pass
        if self.recording:
            self._stop_recording()
        self._finalize_history_entry(call)
        self._forget_call(call)
        self._remove_leg_from_conference(call)
        # Só cessa o ringback se quem caiu é a chamada ativa/tocando; a queda
        # da perna em espera (ex.: re-INVITE de hold recusado pelo PBX) não
        # pode silenciar o toque da chamada nova que ainda está chamando.
        if call is self.current_call:
            self._stop_ringback(reason="chamada atual encerrada")
        nxt = self._pick_other_call(exclude=call)
        if nxt is not None:
            self._activate_call(nxt)
        else:
            self.current_call = None
            self.incoming_call = None
            self.current_audio_media = None
            self.muted = False
            self.btn_mute.config(text="Mute")
            self._teardown_video_ui()
            self.set_call_state("IDLE")

    def _finalize_history_entry(self, call):
        """Grava status (atendida/perdida/recusada) e duração no histórico."""
        try:
            cid = call.getId()
        except Exception:
            cid = None
        start = self._call_started.pop(cid, None) if cid is not None else None
        idx = getattr(call, "_history_idx", None)
        if idx is None or not (0 <= idx < len(self.history)):
            return
        entry = self.history[idx]
        zrtp_state = self._get_zrtp_state(call)
        if zrtp_state is not None:
            entry["secure"] = bool(zrtp_state.get("secure"))
        kind = entry.get("kind") or ""
        status = entry.get("status") or ""
        if not status:
            if kind == "incoming":
                if getattr(call, "_forwarded", False):
                    status = "Encaminhada"
                elif start is not None:
                    status = "Atendida"
                elif getattr(call, "_user_hangup", False):
                    status = "Recusada"
                else:
                    status = "Perdida"
                    label = entry.get("label", "")
                    num = self._dialable_from_uri(label[len("Entrada de "):]) if label.startswith("Entrada de ") else ""
                    notify_send("Chamada perdida", num or "Número desconhecido", "normal")
            elif kind == "outgoing":
                status = "Atendida" if start is not None else "Não atendida"
            elif kind == "transfer" and start is not None:
                status = "Transferida"
        if not entry.get("duration"):
            entry["duration"] = self._format_duration(start) if start else ""
        if status or entry.get("duration"):
            entry["status"] = status
            save_history(self.history)

    @staticmethod
    def _format_duration(start):
        if not start:
            return ""
        elapsed = max(0, int(time.time() - start))
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        if m:
            return f"{m}:{s:02d}"
        return f"{s}s"

    def toggle_hold(self):
        if self.conf_active:
            messagebox.showinfo(
                "Espera",
                "Durante a conferência use os botões de conferência para gerenciar as pernas.",
            )
            return
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

    # =========================
    # CONFERÊNCIA (3ª via)
    # =========================
    def _call_audio_media(self, call):
        """Retorna a AudioMedia ativa de uma chamada confirmada (ou None)."""
        try:
            ci = call.getInfo()
        except Exception:
            return None
        for mi in ci.media:
            if (
                mi.type == pj.PJMEDIA_TYPE_AUDIO
                and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE
            ):
                try:
                    med = call.getMedia(mi.index)
                except Exception as e:
                    logging.warning("Falha ao obter mídia da chamada: %s", e)
                    return None
                return pj.AudioMedia.typecastFromMedia(med)
        return None

    def _conference_devices(self):
        adm = self.endpoint.audDevManager()
        return adm.getCaptureDevMedia(), adm.getPlaybackDevMedia()

    def toggle_conference(self):
        if self.conf_active:
            self.exit_conference()
        else:
            self.start_conference()

    def start_conference(self):
        if self.conf_active:
            return
        call = self.current_call
        if call is None or self.call_state != "IN_CALL" or not self._call_is_confirmed(call):
            messagebox.showwarning(
                "Conferência", "É preciso estar em uma chamada ativa para iniciar a conferência."
            )
            return
        audio = self._call_audio_media(call)
        if audio is None:
            messagebox.showwarning(
                "Conferência", "A chamada ainda não possui áudio ativo."
            )
            return
        try:
            mic, spk = self._conference_devices()
            self._disconnect_call_media()
            if not self.muted:
                mic.startTransmit(audio)
            audio.startTransmit(spk)
            cid = call.getId()
            self.conf_media[cid] = audio
            self.conf_active = True
            self.record_call("Conferência iniciada")
            logging.info("Conferência iniciada com a chamada %s", cid)
            # Puxa TODAS as outras chamadas confirmadas (ativas ou em espera)
            # para dentro da conferência. Suporta o fluxo natural de telefone:
            # "A em espera + B ativa -> Conferência junta as duas". As pernas em
            # espera são retomadas (reinvite); quando a mídia reativa,
            # on_call_media_state (conf-aware) as conecta ao mix.
            others = []
            for other_cid, c in list(self.calls.items()):
                if other_cid == cid:
                    continue
                if self._call_is_confirmed(c):
                    others.append((other_cid, c))
            for other_cid, c in others:
                if other_cid in self.held_calls:
                    self._unhold_call(c)
                self._add_leg_to_conference(c)
            self.update_call_ui()
        except Exception as e:
            logging.error("Erro ao iniciar conferência: %s", e)
            self._teardown_conference()
            messagebox.showerror("Conferência", f"Falha ao iniciar a conferência: {e}")

    def _add_leg_to_conference(self, call):
        if not self.conf_active:
            return
        try:
            cid = call.getId()
        except Exception:
            return
        audio = self._call_audio_media(call)
        if audio is None:
            return
        prev_audio = self.conf_media.get(cid)
        try:
            mic, spk = self._conference_devices()
            # (Re)conecta a perna aos dispositivos locais. Necessário também
            # quando a mídia foi renovada após hold/unhold: nesse caso a perna
            # já está em conf_media, mas o objeto de áudio é novo e as pontes
            # mic/alto-falante não existem mais -- sem isto a perna fica muda.
            if prev_audio is not None and prev_audio is not audio:
                for other_audio in list(self.conf_media.values()):
                    if other_audio is prev_audio:
                        continue
                    try:
                        prev_audio.stopTransmit(other_audio)
                    except Exception:
                        pass
                    try:
                        other_audio.stopTransmit(prev_audio)
                    except Exception:
                        pass
            if not self.muted:
                mic.startTransmit(audio)
            audio.startTransmit(spk)
            # Conexão cruzada com as demais pernas -- por perna, com try/except:
            # uma perna com mídia ainda inativa/stale (ex.: recém-retomada do
            # hold) não pode abortar o acréscimo das demais.
            for other_audio in list(self.conf_media.values()):
                if other_audio is audio:
                    continue
                try:
                    audio.startTransmit(other_audio)
                except Exception:
                    pass
                try:
                    other_audio.startTransmit(audio)
                except Exception:
                    pass
            self.conf_media[cid] = audio
            self.held_calls.discard(cid)
            logging.info("Perna %s adicionada à conferência (3 vias)", cid)
        except Exception as e:
            logging.error("Erro ao adicionar perna %s à conferência: %s", cid, e)

    def _remove_leg_from_conference(self, call):
        if not self.conf_active:
            return
        try:
            cid = call.getId()
        except Exception:
            return
        audio = self.conf_media.pop(cid, None)
        if audio is None:
            return
        try:
            mic, spk = self._conference_devices()
            try:
                mic.stopTransmit(audio)
            except Exception:
                pass
            try:
                audio.stopTransmit(spk)
            except Exception:
                pass
            for other_audio in list(self.conf_media.values()):
                try:
                    audio.stopTransmit(other_audio)
                except Exception:
                    pass
                try:
                    other_audio.stopTransmit(audio)
                except Exception:
                    pass
            logging.info("Perna %s removida da conferência", cid)
        except Exception as e:
            logging.error("Erro ao remover perna %s da conferência: %s", cid, e)
        if not self.conf_media:
            self._teardown_conference()
            logging.info("Conferência encerrada (sem pernas restantes)")

    def _teardown_conference(self):
        media = list(self.conf_media.values())
        self.conf_media = {}
        self.conf_active = False
        if not media:
            return
        try:
            mic, spk = self._conference_devices()
        except Exception:
            return
        for audio in media:
            try:
                mic.stopTransmit(audio)
            except Exception:
                pass
            try:
                audio.stopTransmit(spk)
            except Exception:
                pass
            for other in media:
                if other is audio:
                    continue
                try:
                    audio.stopTransmit(other)
                except Exception:
                    pass

    def exit_conference(self):
        if not self.conf_active:
            return
        legs = [self.calls[cid] for cid in list(self.conf_media) if cid in self.calls]
        self._teardown_conference()
        self.current_audio_media = None
        if legs:
            nxt = self.current_call if self.current_call in legs else legs[0]
            for c in legs:
                if c is not nxt and self._call_is_confirmed(c):
                    self._hold_call(c)
            self._activate_call(nxt)
        else:
            self.current_call = None
            self.incoming_call = None
            self.muted = False
            self.set_call_state("IDLE")
        self.record_call("Conferência encerrada")
        self.update_call_ui()

    def pickup_call(self):
        code = self.pickup_code
        self.number.delete(0, tk.END)
        self.number.insert(0, code)
        self.make_call()

    def redial(self):
        if not self._last_number:
            messagebox.showinfo("Rediscar", "Nenhum número discado ainda.")
            return
        self.number.delete(0, tk.END)
        self.number.insert(0, self._last_number)
        self.make_call()

    def _dial_code(self, code):
        code = (code or "").strip()
        if not code:
            messagebox.showinfo("Recursos", "Nenhum código configurado para este recurso.")
            return
        self.number.delete(0, tk.END)
        self.number.insert(0, code)
        self.make_call()

    def dial_dnd(self):
        self._dial_code(self.dnd_code)

    def dial_forward(self):
        code = (self.forward_code or "").strip()
        if not code:
            messagebox.showinfo("Encaminhar", "Nenhum código de encaminhamento configurado.")
            return
        dest = simpledialog.askstring(
            "Encaminhar", "Número de destino do encaminhamento (vazio = usar só o código):",
            parent=self.root,
        )
        number = f"{code}{clean_extension(dest or '')}"
        self.number.delete(0, tk.END)
        self.number.insert(0, number)
        self.make_call()

    def toggle_auto_answer(self):
        if hasattr(self, "_auto_answer_var"):
            self.auto_answer = bool(self._auto_answer_var.get())
        else:
            self.auto_answer = not self.auto_answer
        self.config_data["auto_answer"] = self.auto_answer
        save_config(self.config_data)
        logging.info("Auto-atender %s", "ativado" if self.auto_answer else "desativado")

    def dial_autoanswer(self):
        self._dial_code(self.autoanswer_code)

    def _connect_call_media(self, call):
        if self.conf_active:
            self._add_leg_to_conference(call)
            return
        try:
            ci = call.getInfo()
        except Exception as e:
            logging.warning("Sessão de chamada já encerrada no media state: %s", e)
            return
        try:
            has_video = False
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
                elif (
                    mi.type == pj.PJMEDIA_TYPE_VIDEO
                    and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE
                ):
                    if self._attach_remote_video(mi):
                        has_video = True
            if has_video:
                self._show_video_area(True)
            else:
                self._teardown_video_ui()
            self._update_video_info(call)
        except Exception as e:
            logging.error("Erro de mídia na chamada: %s", e)

    def _update_video_info(self, call=None):
        label = self.video_info_label
        if label is None or not label.winfo_exists():
            return
        call = call or self.current_call
        if call is None:
            label.config(text="")
            return
        try:
            info = call.getInfo()
            for media in info.media:
                if media.type == pj.PJMEDIA_TYPE_VIDEO and media.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                    stream = call.getStreamInfo(media.index)
                    codec = getattr(stream, "codecName", "vídeo") or "vídeo"
                    label.config(text=f"Codec: {codec}  •  Resolução: automática  •  FPS: automático")
                    return
        except Exception as e:
            logging.debug("Informações de vídeo indisponíveis: %s", e)
        label.config(text="Vídeo aguardando mídia")

    def _attach_remote_video(self, mi):
        try:
            if mi.videoIncomingWindowId == pj.PJSUA_INVALID_ID:
                return False
        except Exception:
            return False
        try:
            win = mi.videoWindow
        except Exception as e:
            logging.warning("Vídeo remoto indisponível: %s", e)
            return False
        if win is None:
            return False
        self.open_video()
        self._remote_window = win
        frame = self.video_box
        if frame is None or not frame.winfo_exists():
            return False
        try:
            frame.update_idletasks()
            xid = frame.winfo_id()
        except Exception as e:
            logging.warning("Não foi possível obter a janela de vídeo: %s", e)
            return False
        try:
            if self.video_placeholder is not None:
                self.video_placeholder.pack_forget()
            win.setWindow(_native_video_handle(xid))
            win.Show(True)
            logging.info("Vídeo remoto anexado à janela do app (xid=%s)", xid)
            return True
        except Exception as e:
            logging.warning("Não foi possível anexar o vídeo remoto: %s", e)
            return False

    def _show_video_area(self, show=True):
        if show:
            self.open_video()

    def _teardown_video_ui(self):
        self._remote_window = None
        box = self.video_box
        if box is not None:
            try:
                box.configure(bg="black")
                if self.video_placeholder is not None:
                    self.video_placeholder.pack(expand=True, fill=tk.BOTH)
            except Exception:
                pass

    def on_call_media_state(self, call):
        if self.conf_active:
            # Em conferência, (re)conecta a perna cuja mídia acabou de mudar,
            # mesmo que não seja a current_call: ao retomar do hold a mídia é
            # reativada num objeto novo e precisa reconectar-se ao mix, senão
            # a perna fica muda e a 3 vias não se forma.
            self._add_leg_to_conference(call)
            if call is self.current_call:
                self._update_zrtp_ui(call)
        elif call is self.current_call:
            self._connect_call_media(call)
            self._update_zrtp_ui(call)
            if self.current_audio_media is not None and not self._call_is_confirmed(call):
                self._stop_ringback(reason="mídia antecipada (early media)")
                logging.info("Mídia antecipada ativa durante o chamado (early media); ringback parado")
        self.update_call_ui()

    def _get_zrtp_state(self, call):
        """Estado de criptografia de mídia da chamada.

        ZRTP só existe em builds patcheados do PJSIP. Neste build (vanilla
        2.15) a criptografia real é SRTP (SDES ou DTLS-SRTP), detectada pelos
        perfis de mídia do SDP negociado (RTP/SAVP / UDP/TLS/RTP/SAVP).
        """
        if call is None:
            return None
        if self.zrtp_available:
            try:
                info = call.getInfo()
                zrtp = getattr(info, "zrtpInfo", None)
                if zrtp is not None:
                    secure = bool(getattr(zrtp, "secure", False) or getattr(zrtp, "active", False))
                    sas = str(getattr(zrtp, "sas", "") or getattr(zrtp, "sasValue", "") or "")
                    verified = bool(getattr(zrtp, "sasVerified", False) or getattr(zrtp, "verified", False))
                    return {"secure": secure, "sas": sas, "verified": verified, "kind": "ZRTP"}
            except Exception:
                pass
        return {
            "secure": bool(getattr(call, "secure_media", False)),
            "sas": "",
            "verified": False,
            "kind": "SRTP",
        }

    def _update_zrtp_ui(self, call=None):
        call = call or self.current_call
        state = self._get_zrtp_state(call)
        if call is not None:
            try:
                self._zrtp_state[call.getId()] = state
            except Exception:
                pass
        label = self.zrtp_label
        if label is None or not label.winfo_exists():
            return
        if state is not None and state.get("secure"):
            kind = state.get("kind") or "SRTP"
            if kind == "ZRTP":
                suffix = "Verificado" if state.get("verified") else "confirme o SAS"
                text = f"Cripto: 🔒 ZRTP {suffix}"
            else:
                text = "Cripto: 🔒 SRTP ativo"
            label.config(text=text, foreground=COLOR_SUCCESS)
            return
        sec = self.config_data.get("security") or {}
        srtp = str(sec.get("srtp") or "disabled")
        if state is not None:
            # Em chamada sem criptografia de mídia
            if srtp == "mandatory":
                label.config(text="Cripto: ⚠ SRTP exigido não negociado", foreground=COLOR_WARNING)
            else:
                label.config(text="Cripto: 🔓 sem criptografia", foreground=COLOR_WARNING)
            return
        if self.zrtp_available:
            label.config(text="ZRTP: disponível", foreground=COLOR_MUTED)
        elif srtp == "mandatory":
            label.config(text="Cripto: SRTP obrigatório", foreground=COLOR_TEXT)
        elif srtp == "optional":
            label.config(text="Cripto: SRTP opcional", foreground=COLOR_MUTED)
        else:
            label.config(text="Cripto: desativada", foreground=COLOR_WARNING)

    def _verify_zrtp_sas(self):
        call = self.current_call
        verifier = getattr(call, "zrtpSasVerified", None) if call is not None else None
        if not callable(verifier):
            self.show_toast("ZRTP não está disponível neste build do PJSIP")
            return
        try:
            verifier(True)
            self._update_zrtp_ui(call)
            self.show_toast("SAS ZRTP confirmado")
        except Exception as e:
            logging.warning("Falha ao confirmar SAS ZRTP: %s", e)

    def set_call_state(self, state):
        self.call_state = state
        if state == "IDLE":
            self._stop_call_timer()
            self.update_presence()
        else:
            label = STATE_LABELS.get(state, state)
            self.status_label.config(text=f"Status: {label}")
            self.status_canvas.itemconfig(self.status_dot, fill=STATUS_COLORS.get(state, COLOR_MUTED))
            self._sync_call_timer()
            if state in ("IN_CALL", "HOLD"):
                self._update_zrtp_ui()
        if state == "INCOMING":
            self._blink_answer(True)
            self._start_ringtone()
            self._notify_incoming()
        else:
            self._blink_answer(False)
            self._stop_ringtone()
            if self.root.title() != self._base_title:
                self.root.title(self._base_title)
        self._publish_presence()

    def _sync_call_timer(self):
        """Inicia/pausa o cronômetro da chamada atual conforme o estado."""
        call = self.current_call
        if call is None or self.call_state not in ("IN_CALL", "HOLD"):
            self._stop_call_timer()
            return
        try:
            cid = call.getId()
        except Exception:
            self._stop_call_timer()
            return
        if cid not in self._call_started:
            logging.info("Cronômetro não iniciado: call_id=%s não está em _call_started (chaves: %s)",
                         cid, list(self._call_started.keys()))
            self._stop_call_timer()
            return
        if self._timer_job is None:
            logging.info("Cronômetro iniciado para call_id=%s", cid)
            self._update_call_timer()

    def _set_timer_text(self, text):
        if not hasattr(self, "timer_label"):
            return
        if text:
            self.timer_label.config(text=text, bg=COLOR_HEADER_CHIP)
        else:
            self.timer_label.config(text="", bg=COLOR_HEADER)

    def _update_call_timer(self):
        """Atualiza o cronômetro (1 tick/segundo)."""
        call = self.current_call
        start = None
        if call is not None:
            try:
                start = self._call_started.get(call.getId())
            except Exception:
                start = None
        if start is None:
            self._timer_job = None
            self._set_timer_text("")
            return
        elapsed = max(0, int(time.time() - start))
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        if h:
            text = f"{h}:{m:02d}:{s:02d}"
        else:
            text = f"{m}:{s:02d}"
        self._set_timer_text(text)
        self._update_qos_label()
        self._timer_job = self.root.after(1000, self._update_call_timer)

    def _stop_call_timer(self):
        if self._timer_job is not None:
            try:
                self.root.after_cancel(self._timer_job)
            except Exception:
                pass
            self._timer_job = None
        self._set_timer_text("")
        self._latest_qos = None
        self._update_qos_label()

    def _read_qos(self):
        call = self.current_call
        if call is None or self.call_state not in ("IN_CALL", "HOLD"):
            return None
        try:
            ci = call.getInfo()
        except Exception:
            return None
        for mi in ci.media:
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                try:
                    stat = call.getStreamStat(mi.index)
                except Exception:
                    return None
                rtcp = stat.rtcp
                rtt_ms = self._qos_number(rtcp.rttUsec) / 1000.0
                jitter_ms = self._qos_number(rtcp.rxStat.jitterUsec) / 1000.0
                # rxStat.loss é o total acumulado de pacotes perdidos (contador,
                # ao lado de pkt/bytes/discard) -- NÃO a fração RTCP 0-255. A
                # perda real = perdidos / (recebidos + perdidos).
                pkt = self._qos_number(rtcp.rxStat.pkt)
                lost = self._qos_number(rtcp.rxStat.loss)
                total = pkt + lost
                loss_pct = round(lost * 100.0 / total, 1) if total > 0 else 0.0
                return rtt_ms, jitter_ms, loss_pct
        return None

    @staticmethod
    def _qos_number(value):
        """Extrai número de campos pjsua2 simples ou MathStat."""
        if isinstance(value, (int, float)):
            return float(value)
        for attr in ("mean", "last", "max", "min"):
            try:
                candidate = getattr(value, attr)
                if isinstance(candidate, (int, float)):
                    return float(candidate)
            except Exception:
                continue
        return 0.0

    def _update_qos_label(self):
        label = getattr(self, "qos_label", None)
        if label is None or not label.winfo_exists():
            return
        try:
            qos = self._read_qos()
        except Exception as e:
            logging.debug("Estatísticas QoS indisponíveis: %s", e)
            qos = None
        if qos is None:
            self._latest_qos = None
            label.config(text="")
            return
        rtt_ms, jitter_ms, loss_pct = qos
        self._latest_qos = (rtt_ms, jitter_ms, loss_pct)
        self.qos_history["timestamp"].append(datetime.now().strftime("%H:%M:%S"))
        self.qos_history["jitter"].append(jitter_ms)
        self.qos_history["loss"].append(loss_pct)
        self.qos_history["rtt"].append(rtt_ms)
        for key in self.qos_history:
            if len(self.qos_history[key]) > self._qos_max_points:
                self.qos_history[key].pop(0)
        label.config(
            text=f"QoS: jitter {jitter_ms:.0f} ms · perda {loss_pct}% · latência (RTT) {rtt_ms:.0f} ms"
        )
        quality = self._qos_quality(qos)
        label.configure(foreground={"good": COLOR_SUCCESS, "medium": COLOR_WARNING, "bad": COLOR_DANGER}[quality])
        if self.qos_graph_win is not None:
            self.qos_graph_win.draw()

    @staticmethod
    def _qos_quality(qos):
        if not qos:
            return "good"
        rtt_ms, jitter_ms, loss_pct = qos
        if jitter_ms > 100 or loss_pct > 10 or rtt_ms > 500:
            return "bad"
        if jitter_ms > 50 or loss_pct > 5 or rtt_ms > 300:
            return "medium"
        return "good"

    def open_qos_graph(self):
        if self.qos_graph_win is not None:
            try:
                self.qos_graph_win.win.deiconify()
                self.qos_graph_win.win.lift()
                return
            except tk.TclError:
                self.qos_graph_win = None
        self.qos_graph_win = QosGraphWindow(self.root, self)

    def update_presence(self):
        """Reflete o registro SIP no indicador quando ocioso:
        Disponível (verde) somente se houver conta logada; caso contrário,
        Offline (cinza) -- ou "Backend indisponível" se pjsua2 falta (Win/Mac)."""
        if self.call_state != "IDLE":
            return
        if any(entry["status"] == "ONLINE" for entry in self.accounts):
            self.status_label.config(text=f"Status: {STATE_LABELS['IDLE']}")
            self.status_canvas.itemconfig(self.status_dot, fill=STATUS_COLORS["IDLE"])
        else:
            if not self._sip_available:
                self.status_label.config(text="Status: Backend SIP indisponível")
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
        if getattr(self, "_contact_ringtone", "") and os.path.isfile(self._contact_ringtone):
            return self._contact_ringtone
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
        if self.endpoint is None:
            messagebox.showinfo("Toque", "Backend SIP indisponível; use o player do sistema.")
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

    def _make_tone_gen(self, freq, on_msec, off_msec):
        """Cria um ToneGenerator em loop (sem transmitir)."""
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
        return tg

    def _play_tone(self, freq, on_msec, off_msec):
        """Cria um tom em loop e o transmite ao dispositivo de saída."""
        tg = self._make_tone_gen(freq, on_msec, off_msec)
        spk = self.endpoint.audDevManager().getPlaybackDevMedia()
        tg.startTransmit(spk)
        return tg

    def _start_moh(self, call):
        try:
            cid = call.getId()
        except Exception:
            return
        if cid in self._moh:
            return
        audio = self._call_audio_media(call)
        if audio is None:
            return
        try:
            moh_path = resource_path("moh.wav")
            if os.path.isfile(moh_path):
                player = pj.AudioMediaPlayer()
                player.createPlayer(moh_path, 0)  # 0 = loop
            else:
                player = self._make_tone_gen(440, 800, 200)
            player.startTransmit(audio)
            self._moh[cid] = (player, audio)
            logging.info("Music on Hold iniciado para a chamada %s", cid)
        except Exception as e:
            logging.error("Falha ao iniciar Music on Hold: %s", e)

    def _stop_moh(self, call):
        try:
            cid = call.getId()
        except Exception:
            return
        moh = self._moh.pop(cid, None)
        if moh is None:
            return
        player, audio = moh
        try:
            player.stopTransmit(audio)
        except Exception:
            pass
        logging.info("Music on Hold encerrado para a chamada %s", cid)

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
        self._contact_ringtone = ""
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

    def _stop_ringback(self, reason=""):
        if self._ringback is None:
            return
        if reason:
            logging.info("Parando ringback: %s", reason)
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
        can_hangup = self.current_call is not None and not self.conf_active
        if can_hangup:
            self.btn_call.config(
                text="⏹  Desligar", command=self.hangup,
                bg=COLOR_DANGER, fg="#FFFFFF", state=tk.NORMAL
            )
        else:
            self.btn_call.config(
                text="📞  Ligar", command=self.make_call,
                bg=COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG,
                state=tk.NORMAL if (not busy or self.conf_active) else tk.DISABLED
            )
        # btn_answer agora e multi-estado:
        #   INCOMING            -> "Atender"      (answer)
        #   conf_active + IN_CALL -> "Sair conf."  (exit_conference)
        #   conf_active (discando) -> desativado   (não desfaz no meio do acréscimo)
        #   IN_CALL confirm     -> "Conferencia"   (toggle_conference)
        #   demais              -> desativado
        if self.call_state == "INCOMING":
            self.btn_answer.config(
                text="✅  Atender", command=self.answer,
                bg=COLOR_PRIMARY, fg="#FFFFFF", state=tk.NORMAL,
            )
        elif self.conf_active and self.call_state == "IN_CALL":
            self.btn_answer.config(
                text="↩  Sair da conf.", command=self.exit_conference,
                bg=COLOR_DANGER, fg="#FFFFFF", state=tk.NORMAL,
            )
        elif self.conf_active:
            self.btn_answer.config(
                text="👥  Conf. ativa", command=self.exit_conference,
                bg=COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG, state=tk.DISABLED,
            )
        elif (
            self.current_call is not None
            and self.call_state == "IN_CALL"
            and self._call_is_confirmed(self.current_call)
        ):
            self.btn_answer.config(
                text="👥  Conferência", command=self.toggle_conference,
                bg=COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG, state=tk.NORMAL,
            )
        else:
            self.btn_answer.config(
                text="✅  Atender", command=self.answer,
                bg=COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG, state=tk.DISABLED,
            )
        self.btn_mute.config(
            state=tk.NORMAL if self.current_audio_media is not None else tk.DISABLED
        )
        if hasattr(self, "btn_record"):
            self.btn_record.config(
                state=tk.NORMAL if self.current_audio_media is not None else tk.DISABLED
            )
            self._update_record_btn()
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
        if hasattr(self, "btn_video"):
            self._update_video_btn()
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
    # GRAVAÇÃO DE CHAMADAS
    # =========================
    @staticmethod
    def _record_dir():
        return os.path.join(platform.music_dir(), "VoiceNeves")

    def _current_call_extension(self):
        acc = getattr(self.current_call, "acc", None)
        if acc is not None:
            return clean_extension(acc.data.get("user", "")) or "desconhecido"
        return "desconhecido"

    def _current_call_number(self):
        call = self.current_call
        if call is None:
            return ""
        try:
            remote = call.getInfo().remoteUri
        except Exception:
            return ""
        return self._dialable_from_uri(remote)

    def toggle_record(self):
        if self.recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        if self.recording:
            return
        if self.current_audio_media is None:
            messagebox.showwarning("Gravar", "Nenhuma chamada ativa para gravar.")
            return
        try:
            os.makedirs(self._record_dir(), exist_ok=True)
        except OSError as e:
            logging.error("Falha ao criar diretório de gravação: %s", e)
            messagebox.showerror("Gravar", f"Não foi possível criar o diretório de gravação:\n{e}")
            return
        ramal = self._current_call_extension()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self._record_dir(), f"{ts}.{ramal}.wav")
        try:
            rec = pj.AudioMediaRecorder()
            rec.createRecorder(path)
            mic = self.endpoint.audDevManager().getCaptureDevMedia()
            mic.startTransmit(rec)
            self.current_audio_media.startTransmit(rec)
            self.recorder = rec
            self.recording = True
            self.record_path = path
            self._record_number = self._current_call_number()
            logging.info("Gravação iniciada: %s", path)
        except Exception as e:
            self.recorder = None
            self.recording = False
            logging.error("Falha ao iniciar gravação: %s", e)
            messagebox.showerror("Gravar", f"Falha ao iniciar a gravação:\n{e}")
            return
        self._update_record_btn()

    def _stop_recording(self):
        if not self.recording:
            return
        try:
            mic = self.endpoint.audDevManager().getCaptureDevMedia()
            if self.recorder is not None:
                try:
                    mic.stopTransmit(self.recorder)
                except Exception:
                    pass
                if self.current_audio_media is not None:
                    try:
                        self.current_audio_media.stopTransmit(self.recorder)
                    except Exception:
                        pass
        except Exception as e:
            logging.error("Falha ao parar gravação: %s", e)
        finally:
            self.recorder = None
            self.recording = False
        path = self.record_path
        number = self._record_number
        self.record_path = ""
        self._record_number = ""
        if path:
            logging.info("Gravação finalizada: %s", path)
            self.history.append(
                {
                    "ts": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "label": f"Gravação de {number or 'desconhecido'}",
                    "kind": "recording",
                    "status": "",
                    "duration": "",
                    "secure": False,
                }
            )
            if len(self.history) > 500:
                self.history = self.history[-500:]
            save_history(self.history)
        self._update_record_btn()

    def _update_record_btn(self):
        if not hasattr(self, "btn_record"):
            return
        if self.recording:
            self.btn_record.config(text="⏺  Gravando...", bg=COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG)
        else:
            self.btn_record.config(text="⏺  Gravar", bg=COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG)

    # =========================
    # VÍDEO
    # =========================
    def toggle_video(self):
        if not self._has_video:
            messagebox.showinfo("Vídeo indisponível", "O pjsua deste sistema não suporta vídeo.")
            return
        self.video_enabled = not self.video_enabled
        self._update_video_btn()
        call = self.current_call
        if call is None or not self._call_is_confirmed(call) or self.call_state != "IN_CALL":
            return
        try:
            op = pj.CallOpParam(False)
            op.opt.audioCount = 1
            op.opt.videoCount = 1 if self.video_enabled else 0
            op.opt.flag = pj.PJSUA_CALL_UPDATE_CONTACT
            self._apply_video_call_options(op)
            call.reinvite(op)
            logging.info("Vídeo %s na chamada atual", "ativado" if self.video_enabled else "desativado")
        except Exception as e:
            logging.error("Erro ao atualizar vídeo na chamada: %s", e)

    def _update_video_btn(self):
        if not hasattr(self, "btn_video"):
            return
        if not self._has_video:
            self.btn_video.config(
                text="📹  Vídeo", bg=COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG, state="disabled"
            )
            return
        if self.video_enabled:
            self.btn_video.config(text="📹  Vídeo ON", bg=COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG)
        else:
            self.btn_video.config(text="📹  Vídeo", bg=COLOR_KEYPAD_BG, fg=COLOR_KEYPAD_FG)

    def _find_screen_device(self):
        try:
            for index, device in enumerate(self.endpoint.vidDevManager().enumDev2()):
                name = str(getattr(device, "name", "") or "").lower()
                if any(token in name for token in ("screen", "desktop", "x11", "kms", "display")):
                    return index
        except Exception as e:
            logging.warning("Não foi possível localizar captura de tela: %s", e)
        return -1

    def _reinvite_video_device(self, device_id):
        call = self.current_call
        if call is None or self.call_state != "IN_CALL" or not self._call_is_confirmed(call):
            return False
        try:
            try:
                self.endpoint.vidDevManager().switchDev(device_id)
            except Exception as e:
                logging.debug("Troca global de dispositivo de vídeo indisponível: %s", e)
            op = pj.CallOpParam(False)
            op.opt.audioCount = 1
            op.opt.videoCount = 1
            op.opt.flag = pj.PJSUA_CALL_UPDATE_CONTACT
            self._apply_video_call_options(op, device_id)
            call.reinvite(op)
            return True
        except Exception as e:
            logging.error("Falha ao atualizar dispositivo de vídeo: %s", e)
            self.show_toast(f"Não foi possível atualizar o vídeo: {e}")
            return False

    def _apply_video_call_options(self, op, device_id=None):
        """Aplica opções expostas pela versão atual do pjsua2 sem exigir campos ausentes."""
        if device_id is not None and device_id >= 0:
            try:
                op.opt.videoCaptureDevice = device_id
            except AttributeError:
                pass
        try:
            bandwidth = int((self.config_data.get("video") or {}).get("video_bandwidth", 0))
            if bandwidth > 0:
                op.opt.videoBandwidth = bandwidth
        except (AttributeError, TypeError, ValueError):
            pass

    def _toggle_screen_sharing(self):
        if not self._has_video:
            self.show_toast("Vídeo indisponível neste sistema")
            return
        if self._screen_shared:
            device_id = self._selected_camera()
            if device_id < 0:
                device_id = (self.config_data.get("video") or {}).get("device", -1)
            if device_id >= 0 and self._reinvite_video_device(device_id):
                self._screen_shared = False
                self.show_toast("Câmera restaurada")
            return
        screen_id = self._find_screen_device()
        if screen_id < 0:
            self.show_toast("Nenhum dispositivo de captura de tela foi encontrado")
            return
        if self._reinvite_video_device(screen_id):
            self._screen_device_id = screen_id
            self._screen_shared = True
            self.show_toast("Compartilhamento de tela ativado")

    def _toggle_video_fullscreen(self):
        if self.video_win is None:
            return
        self._video_fullscreen = not self._video_fullscreen
        try:
            self.video_win.attributes("-fullscreen", self._video_fullscreen)
        except tk.TclError:
            pass

    def _take_video_snapshot(self):
        self.show_toast("Captura de frame ainda não é exposta pelo pjsua2 desta versão")

    def _save_video_settings(self):
        if self.video_win is None:
            return
        try:
            bandwidth = max(0, int(self.video_bandwidth_spin.get()))
        except (TypeError, ValueError):
            bandwidth = 0
        resolution = self.video_resolution_box.get() or "auto"
        video = self.config_data.setdefault("video", {})
        video["video_bandwidth"] = bandwidth
        video["video_resolution"] = resolution
        save_config(self.config_data)
        if self.current_call is not None and self.call_state == "IN_CALL":
            self._reinvite_video_device(self._selected_camera())
        self.show_toast("Qualidade de vídeo salva")

    # =========================
    # DISPOSITIVOS
    # =========================
    def load_devices(self):
        if self.endpoint is None:
            # Sem backend SIP (Win/Mac): nada a listar. Comboboxes ficam vazios.
            return
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

        cams = []
        try:
            vdevs = self.endpoint.vidDevManager().enumDev2()
            for index, d in enumerate(vdevs):
                if d.dir & pj.PJMEDIA_DIR_CAPTURE:
                    cams.append((index, d.name))
        except Exception as e:
            logging.error("Erro ao listar câmeras: %s", e)

        if self.settings_win is not None:
            self.input_devices["values"] = [f"{i} | {n}" for i, n in ins]
            self.output_devices["values"] = [f"{i} | {n}" for i, n in outs]

        if self.video_win is not None:
            self.video_devices["values"] = [f"{i} | {n}" for i, n in cams]
            saved = (self.config_data.get("video") or {}).get("device", -1)
            current = f"{saved} | ..."
            for label in self.video_devices["values"]:
                if label.startswith(f"{saved} | "):
                    current = label
                    break
            self.video_devices.set(current if saved >= 0 else "")
            if self.btn_screen_share is not None:
                self.btn_screen_share.config(
                    state=tk.NORMAL if self._find_screen_device() >= 0 else tk.DISABLED
                )

    def _selected_camera(self):
        try:
            return int(self.video_devices.get().split(" | ")[0])
        except (ValueError, AttributeError):
            return -1

    def apply_devices(self):
        if self.settings_win is None:
            messagebox.showinfo("Configurações", "Abra Configurações > Áudio para escolher dispositivos.")
            return
        if self.endpoint is None:
            messagebox.showinfo("Backend SIP", "Backend SIP indisponível neste sistema; nada a aplicar.")
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

    def apply_camera(self):
        if self.endpoint is None:
            messagebox.showinfo(
                "Câmera", "Backend SIP indisponível neste sistema; câmera inativa.",
                parent=self.video_win,
            )
            return
        cam = self._selected_camera()
        if cam < 0:
            messagebox.showinfo(
                "Câmera", "Selecione uma câmera na lista acima.", parent=self.video_win
            )
            return
        if cam != (self.config_data.get("video") or {}).get("device", -1):
            video = self.config_data.setdefault("video", {})
            video["device"] = cam
            save_config(self.config_data)
            logging.info("Câmera salva: %s", cam)
            if self.current_call is not None and self.call_state == "IN_CALL":
                self._reinvite_video_device(cam)
            else:
                self._apply_camera_to_accounts(cam)
        self._screen_shared = False
        self.show_toast(f"Câmera {cam} aplicada")

    def _apply_camera_to_accounts(self, dev):
        if self.current_call is not None or self.call_state != "IDLE":
            logging.info("Câmera %s salva; aplicará nas próximas chamadas", dev)
            return
        try:
            for entry in list(self.accounts):
                acc = entry.get("acc")
                if acc is not None:
                    try:
                        acc.shutdown()
                    except Exception:
                        pass
            self.accounts = []
            self.update_presence()
            for a in self.config_data.get("accounts", []):
                self.register_account(a)
            logging.info("Contas re-registradas com a câmera %s", dev)
        except Exception as e:
            logging.error("Erro ao re-registrar contas: %s", e)

    def _toggle_preview(self):
        if self.endpoint is None:
            messagebox.showinfo(
                "Prévia", "Backend SIP indisponível neste sistema; prévia desativada.",
                parent=self.video_win,
            )
            return
        if self._preview is not None:
            self._stop_preview()
            return
        dev = self._selected_camera()
        if dev < 0:
            messagebox.showinfo(
                "Prévia", "Selecione uma câmera na lista acima.", parent=self.video_win
            )
            return
        frame = self.video_preview_frame
        if frame is None or not frame.winfo_exists():
            return
        try:
            frame.update_idletasks()
            xid = frame.winfo_id()
            prm = pj.VideoPreviewOpParam()
            prm.show = True
            # Captura em 640x360 (16:9 nativo da webcam) para casar com o
            # quadro 480x270. Sem format.type=PJMEDIA_TYPE_VIDEO o campo
            # inteiro é descartado e o dispositivo abre no default (720p),
            # que sai distorcido/cortado no quadro.
            prm.format.type = pj.PJMEDIA_TYPE_VIDEO
            prm.format.id = pj.PJMEDIA_FORMAT_I420
            prm.format.width = 640
            prm.format.height = 360
            prm.format.fpsNum = 30
            prm.format.fpsDenum = 1
            prm.window = _native_video_handle(xid)
            self._preview = pj.VideoPreview(dev)
            self._preview.start(prm)
            # Com janela embutida, o SDL herda disp_size do VÍDEO (640x360)
            # em vez da janela real; sem este ajuste a imagem renderiza um
            # terço maior e sai cortada na direita/baixo.
            self.video_preview_label.pack_forget()
            frame.update_idletasks()
            win = self._preview.getVideoWindow()
            size = pj.MediaSize()
            size.w = frame.winfo_width()
            size.h = frame.winfo_height()
            win.setSize(size)
            # Aplica preferência de espelhamento (efeito selfie) salva.
            self._mirror_on = bool(self.config_data.get("preview_mirror"))
            if self._mirror_on:
                win.setMirror(True)
                self.btn_video_mirror.config(text="Espelhado ✓")
            else:
                self.btn_video_mirror.config(text="🪞 Espelhar")
            self.btn_video_preview.config(text="Atual. prévia")
            logging.info("Prévia da câmera %s iniciada", dev)
        except Exception as e:
            self._preview = None
            self.video_preview_label.pack(expand=True, fill=tk.BOTH)
            self.video_preview_label.config(text="Prévia indisponível")
            messagebox.showerror(
                "Prévia", f"Não foi possível iniciar a prévia da câmera:\n{e}",
                parent=self.video_win,
            )

    def _on_preview_area_configure(self, event):
        if getattr(self, "_preview_fit_job", None):
            try:
                self.root.after_cancel(self._preview_fit_job)
            except Exception:
                pass
        self._preview_fit_job = self.root.after(
            60, lambda w=event.width, h=event.height: self._fit_preview_area(w, h)
        )

    def _fit_preview_area(self, area_w, area_h):
        """Centraliza o quadro de vídeo mantendo 16:9 e reajusta o render."""
        self._preview_fit_job = None
        frame = getattr(self, "video_preview_frame", None)
        if frame is None or not frame.winfo_exists():
            return
        pad = 6
        avail_w = max(160, area_w - pad * 2)
        avail_h = max(90, area_h - pad * 2)
        fw, fh = avail_w, int(avail_w * 9 / 16)
        if fh > avail_h:
            fh = avail_h
            fw = int(fh * 16 / 9)
        frame.place(x=(area_w - fw) // 2, y=(area_h - fh) // 2, width=fw, height=fh)
        if self._preview is not None:
            try:
                win = self._preview.getVideoWindow()
                size = pj.MediaSize()
                size.w = int(frame.winfo_width())
                size.h = int(frame.winfo_height())
                if size.w > 0 and size.h > 0:
                    win.setSize(size)
            except Exception:
                pass

    def _toggle_mirror(self):
        if self._preview is None:
            return
        try:
            self._mirror_on = not getattr(self, "_mirror_on", False)
            self._preview.getVideoWindow().setMirror(self._mirror_on)
            self.btn_video_mirror.config(
                text="Espelhado ✓" if self._mirror_on else "🪞 Espelhar"
            )
            self.config_data["preview_mirror"] = self._mirror_on
            save_config(self.config_data)
        except Exception as e:
            logging.warning("Erro ao espelhar prévia: %s", e)

    def _stop_preview(self):
        preview = self._preview
        self._preview = None
        if preview is not None:
            try:
                preview.stop()
            except Exception as e:
                logging.warning("Erro ao parar a prévia: %s", e)
        if self.video_preview_frame is not None:
            try:
                if self.video_preview_frame.winfo_exists():
                    self.video_preview_frame.configure(bg="black")
                    self.video_preview_label.config(text="Prévia desligada")
                    self.video_preview_label.pack(expand=True, fill=tk.BOTH)
            except Exception:
                pass
        if hasattr(self, "btn_video_preview"):
            try:
                self.btn_video_preview.config(text="Ver prévia")
                self.btn_video_mirror.config(text="🪞 Espelhar")
            except Exception:
                pass
        self._mirror_on = False

    # =========================
    # BANDEJA / HOTKEYS / NOTIFICAÇÕES
    # =========================
    def _setup_tray(self):
        self._tray_icon = None
        self._tray_thread = None
        if not HAVE_TRAY:
            logging.info("pystray/PIL indisponíveis; bandeja do sistema desativada")
            return
        if is_wayland() and not appindicator_available():
            logging.warning(
                "Bandeja desativada: no Wayland é preciso o backend AppIndicator. "
                "Instale 'gir1.2-ayatanaappindicator3-0.1' (e 'python3-gi' no ambiente), "
                "e ative a extensão 'AppIndicator' do GNOME."
            )
            return
        try:
            image = PILImage.open(resource_path("Icone.png"))
        except Exception as e:
            logging.warning("Não foi possível carregar o ícone da bandeja (%s); usando padrão", e)
            image = PILImage.new("RGB", (64, 64), (37, 99, 235))

        menu = pystray.Menu(
            pystray.MenuItem("Atender", self._tray_answer),
            pystray.MenuItem("Desligar", self._tray_hangup),
            pystray.MenuItem("Mute/Unmute", self._tray_mute),
            pystray.MenuItem("Abrir", self._tray_open),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", self._tray_quit),
        )
        try:
            self._tray_icon = pystray.Icon("voiceneves", image, APP_NAME, menu)
            self._tray_thread = threading.Thread(
                target=self._tray_icon.run, name="pystray", daemon=True
            )
            self._tray_thread.start()
            self.root.bind("<Unmap>", self._on_minimize)
            logging.info("Bandeja do sistema ativada")
        except Exception as e:
            self._tray_icon = None
            logging.warning("Não foi possível iniciar a bandeja do sistema: %s", e)

    def _on_minimize(self, event=None):
        if event is not None and getattr(event, "widget", None) is not self.root:
            return
        try:
            if self._tray_icon is not None and self.root.wm_state() == "iconic":
                self.root.withdraw()
        except Exception as e:
            logging.warning("Falha ao minimizar para a bandeja: %s", e)

    def _show_window(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception as e:
            logging.warning("Falha ao restaurar a janela: %s", e)

    def _answer_guarded(self):
        if self.call_state == "INCOMING":
            self.answer()

    def _tray_answer(self, icon=None, item=None):
        self._ui(self._answer_guarded)

    def _tray_hangup(self, icon=None, item=None):
        self._ui(self.hangup)

    def _tray_mute(self, icon=None, item=None):
        self._ui(self.toggle_mute)

    def _tray_open(self, icon=None, item=None):
        self._ui(self._show_window)

    def _tray_quit(self, icon=None, item=None):
        self._ui(self.close)

    def _setup_hotkeys(self):
        self._hotkeys = None
        if is_wayland():
            # Wayland não permite hotkeys globais; usa atalhos dentro do app
            # (funcionam quando a janela está em foco).
            try:
                self.root.bind("<F9>", lambda e: self._answer_guarded())
                self.root.bind("<F10>", lambda e: self.hangup())
                self.root.bind("<F11>", lambda e: self.toggle_mute())
                logging.info(
                    "Wayland detectado: F9/F10/F11 ativos com a janela em foco "
                    "(hotkeys globais indisponíveis nesta sessão)"
                )
            except Exception as e:
                logging.warning("Não foi possível registrar os atalhos no Wayland: %s", e)
            return
        if not HAVE_HOTKEYS:
            logging.info("pynput indisponível; hotkeys globais desativadas")
            return
        try:
            self._hotkeys = pynput_keyboard.GlobalHotKeys({
                "<f9>": self._hotkey_answer,
                "<f10>": self._hotkey_hangup,
                "<f11>": self._hotkey_mute,
            })
            self._hotkeys.start()
            logging.info("Hotkeys globais ativas (F9=Atender, F10=Desligar, F11=Mute)")
        except Exception as e:
            self._hotkeys = None
            logging.warning("Não foi possível ativar as hotkeys globais: %s", e)

    def _hotkey_answer(self, *args):
        self._ui(self._answer_guarded)

    def _hotkey_hangup(self, *args):
        self._ui(self.hangup)

    def _hotkey_mute(self, *args):
        self._ui(self.toggle_mute)

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
            if getattr(self, "_theme_proc", None) is not None:
                try:
                    self._theme_proc.terminate()
                except Exception:
                    pass
                self._theme_proc = None
            if getattr(self, "_answer_blink_job", None):
                try:
                    self.root.after_cancel(self._answer_blink_job)
                except Exception:
                    pass
            if self.recording:
                self._stop_recording()
            if self.ldap_manager is not None:
                self.ldap_manager.close()
            if self._hotkeys is not None:
                try:
                    self._hotkeys.stop()
                except Exception:
                    pass
                self._hotkeys = None
            if self._tray_icon is not None:
                try:
                    self._tray_icon.stop()
                except Exception:
                    pass
                self._tray_icon = None
            self._close_transfer_win()
            self._stop_ringback(reason="aplicativo encerrando")
            self._stop_ringtone()
            self._stop_test_player()
            self._stop_preview()
            if self.qos_graph_win is not None:
                try:
                    self.qos_graph_win.close()
                except Exception:
                    pass
                self.qos_graph_win = None
            self._teardown_conference()
            if self.video_win is not None:
                try:
                    self.video_win.destroy()
                except Exception:
                    pass
                self.video_win = None
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
