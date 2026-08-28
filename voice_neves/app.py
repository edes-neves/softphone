"""Interface grafica (Qt/PySide6) + controlador do softphone (pjsua2).

Este modulo concentra a UI (Qt) e o estado do SoftphoneApp. Toda a logica
pura (config, historico, contatos, secrets, ldap, modelos pjsip,
provisioning, updater, cti) vive em modulos separados do pacote voice_neves.
"""
import os
import csv
import json
import time
import logging
import threading
import queue
import subprocess
import webbrowser
from datetime import datetime
from urllib.parse import quote

from PySide6.QtCore import (
    Qt, QTimer, QEvent, QObject, Signal, QRectF,
)
from PySide6.QtGui import (
    QAction, QIcon, QColor, QPen, QFont, QCursor, QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QDialog, QMessageBox, QInputDialog,
    QFileDialog, QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox,
    QRadioButton, QSpinBox, QSlider, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QFrame,
    QHBoxLayout, QVBoxLayout, QGridLayout, QFormLayout, QGroupBox,
    QTabWidget, QScrollArea, QSizePolicy, QAbstractItemView, QGraphicsDropShadowEffect,
)

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

from .constants import *  # noqa: F401,F403
from .constants import DATA_DIR
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
from .provisioning import ProvisioningManager, prov_cache_path
from .updater import Updater


def pj_error_text(e):
    """Formata um erro do pjsua2 (pj.Error) com a mensagem real do PJSIP."""
    if isinstance(e, pj.Error):
        try:
            return e.info().strip() or str(e) or repr(e)
        except Exception:
            return str(e) or repr(e)
    return str(e)


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


# =========================
# TEMA (cores compatíveis com o original)
# =========================
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
COLOR_BTN_DISABLED_BG = THEMES["light"]["btn_disabled_bg"]
COLOR_BTN_DISABLED_FG = THEMES["light"]["btn_disabled_fg"]

_ACTIVE_THEME = "light"


def active_theme():
    return _ACTIVE_THEME


def set_theme(name):
    """Aplica a paleta de cores do tema, atualizando as globais COLOR_*."""
    global COLOR_BG, COLOR_CARD, COLOR_BORDER, COLOR_PRIMARY_DARK
    global COLOR_TEXT, COLOR_MUTED, COLOR_LIST_EVEN, COLOR_LIST_ODD
    global COLOR_HEADER, COLOR_HEADER_CHIP, COLOR_KEYPAD_BG, COLOR_KEYPAD_FG
    global COLOR_TOOLTIP_BG, COLOR_TOOLTIP_FG, _ACTIVE_THEME
    global COLOR_BTN_DISABLED_BG, COLOR_BTN_DISABLED_FG
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
    COLOR_BTN_DISABLED_BG = t["btn_disabled_bg"]
    COLOR_BTN_DISABLED_FG = t["btn_disabled_fg"]
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


STATUS_COLORS = {
    "IDLE": COLOR_SUCCESS,
    "CALLING": COLOR_PRIMARY,
    "RINGING": COLOR_WARNING,
    "INCOMING": COLOR_DANGER,
    "IN_CALL": COLOR_SUCCESS,
    "HOLD": COLOR_WARNING,
}

COLOR_OFFLINE = "#5C4033"

_picked_font = None


def pick_font():
    """Retorna a primeira fonte disponível, memorizando o resultado."""
    global _picked_font
    if _picked_font is not None:
        return _picked_font
    families = set(QFontDatabase_families())
    for name in FONT_CANDIDATES:
        if name in families:
            _picked_font = name
            return name
    _picked_font = "DejaVu Sans"
    return _picked_font


def QFontDatabase_families():
    try:
        from PySide6.QtGui import QFontDatabase
        return QFontDatabase.families()
    except Exception:
        return []


def _native_video_handle(xid):
    """Cria um VideoWindowHandle apontando para uma janela nativa X11 (Qt winId)."""
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
# HELPERS DE UI Qt
# =========================
def _app_qss():
    """Folha de estilo global calculada a partir do tema ativo."""
    return f"""
    QMainWindow, QWidget {{
        background: {COLOR_BG}; color: {COLOR_TEXT};
        font-size: 13px;
    }}
    QLabel {{
        background: transparent; color: {COLOR_TEXT};
    }}
    QLabel[header="true"] {{
        color: #FFFFFF;
    }}
    QLineEdit, QComboBox, QSpinBox {{
        background: {COLOR_CARD}; color: {COLOR_TEXT};
        border: 1px solid {COLOR_BORDER}; border-radius: 8px;
        padding: 6px 9px; selection-background-color: {COLOR_PRIMARY};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {COLOR_PRIMARY};
    }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{
        background: {COLOR_CARD}; color: {COLOR_TEXT};
        selection-background-color: {COLOR_PRIMARY};
        selection-color: #FFFFFF; border: 1px solid {COLOR_BORDER};
    }}
    QCheckBox, QRadioButton {{ background: transparent; color: {COLOR_TEXT}; spacing: 8px; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 18px; height: 18px; }}
    QPushButton {{
        background: {COLOR_CARD}; color: {COLOR_TEXT};
        border: 1px solid {COLOR_BORDER}; border-radius: 10px;
        padding: 8px 12px; font-weight: 600;
    }}
    QPushButton:hover {{ border: 1px solid {COLOR_PRIMARY}; }}
    QPushButton:pressed {{ background: {COLOR_BORDER}; }}
    QPushButton:disabled {{ color: {COLOR_MUTED}; }}
    QGroupBox {{
        background: {COLOR_CARD}; color: {COLOR_TEXT};
        border: 1px solid {COLOR_BORDER}; border-radius: 12px;
        margin-top: 14px; padding: 10px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin; left: 12px; top: 2px;
        color: {COLOR_PRIMARY_DARK}; font-weight: 700;
    }}
    QTabWidget::pane {{ border: 1px solid {COLOR_BORDER}; border-radius: 10px; }}
    QTabBar::tab {{
        background: {COLOR_CARD}; color: {COLOR_TEXT};
        border: 1px solid {COLOR_BORDER}; border-bottom: none;
        padding: 8px 16px; margin-right: 2px; border-top-left-radius: 8px;
        border-top-right-radius: 8px; font-weight: 600;
    }}
    QTabBar::tab:selected {{ background: {COLOR_PRIMARY}; color: #FFFFFF; }}
    QListWidget, QTreeWidget, QTableWidget {{
        background: {COLOR_CARD}; color: {COLOR_TEXT};
        border: 1px solid {COLOR_BORDER}; border-radius: 10px;
        outline: none;
    }}
    QListWidget::item, QTreeWidget::item, QTableWidget::item {{
        padding: 6px; border-radius: 6px;
    }}
    QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
        background: {COLOR_PRIMARY}; color: #FFFFFF;
    }}
    QHeaderView::section {{
        background: {COLOR_CARD}; color: {COLOR_TEXT};
        border: none; border-bottom: 1px solid {COLOR_BORDER};
        padding: 6px; font-weight: 700;
    }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {COLOR_BORDER}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QSlider::groove:horizontal {{ height: 6px; background: {COLOR_BORDER}; border-radius: 3px; }}
    QSlider::handle:horizontal {{
        background: {COLOR_PRIMARY}; width: 18px; height: 18px;
        margin: -6px 0; border-radius: 9px;
    }}
    QMenu {{ background: {COLOR_CARD}; color: {COLOR_TEXT}; border: 1px solid {COLOR_BORDER}; }}
    QMenu::item {{ padding: 6px 24px; }}
    QMenu::item:selected {{ background: {COLOR_PRIMARY}; color: #FFFFFF; }}
    QStatusBar {{ background: {COLOR_CARD}; color: {COLOR_MUTED}; }}
    """


def _shadow(widget, blur=24, dy=4):
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(0, 0, 0, 60))
    widget.setGraphicsEffect(eff)
    return widget


def _decorate_window(win, maximize=True):
    """Garante os botões padrão da janela (minimizar/maximizar/fechar).

    QDialogs costumam abrir com apenas o botão fechar em alguns gerenciadores
    de janela (Linux); aqui somamos os hints de min/max aos já existentes, sem
    remover os flags atuais (preserva modalidade/primeiro plano quando houver).
    """
    win.setWindowFlags(
        win.windowFlags()
        | Qt.WindowType.WindowSystemMenuHint
        | Qt.WindowType.WindowMinimizeButtonHint
        | Qt.WindowType.WindowCloseButtonHint
        | (Qt.WindowType.WindowMaximizeButtonHint if maximize else Qt.WindowType())
    )
    return win


# =========================
# BOTÃO ARREDONDADO (QPushButton estilizado)
# =========================
class RoundedButton(QPushButton):
    """Botão com cantos arredondados. Mantém API parecida com a do original."""

    def __init__(
        self, parent, text="", command=None, bg=COLOR_PRIMARY, fg="#FFFFFF",
        font=None, padx=10, pady=8, radius=12, cursor="pointinghand",
    ):
        super().__init__(text, parent)
        self._text = text
        self._command = command
        self._bg = bg
        self._fg = fg
        self._disabled = False
        if font:
            self.setFont(font)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumHeight(pady * 2 + 22)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor) if cursor == "pointinghand"
                       else QCursor(Qt.CursorShape.ForbiddenCursor))
        self.clicked.connect(self._on_click)
        self._apply_style()

    def _apply_style(self):
        if self._disabled:
            bg, fg = COLOR_BTN_DISABLED_BG, COLOR_BTN_DISABLED_FG
        else:
            bg, fg = self._bg, self._fg
        c = "background: %s; color: %s; border-radius: 12px; border: none; padding: 8px 12px; font-weight: 600;" % (
            bg,
            fg,
        )
        self.setStyleSheet(c)

    def _on_click(self):
        if not self._disabled and self._command is not None:
            self._command()

    def setText(self, text):
        self._text = text
        super().setText(text)

    def set_color(self, bg, fg):
        self._bg = bg
        self._fg = fg
        self._apply_style()

    def set_text_color(self, fg):
        self._fg = fg
        self._apply_style()

    def set_enabled(self, enabled):
        self._disabled = not enabled
        self.setEnabled(enabled)
        self._apply_style()

    def configure(self, **kw):
        if "text" in kw:
            self.setText(kw["text"])
        if "bg" in kw:
            self._bg = kw["bg"]
            self._apply_style()
        if "fg" in kw:
            self._fg = kw["fg"]
            self._apply_style()
        if "command" in kw:
            self._command = kw["command"]
        if "state" in kw:
            self.set_enabled(kw["state"] != "disabled")
        if "font" in kw and kw["font"]:
            self.setFont(kw["font"])
        return self

    def cget(self, key):
        if key == "text":
            return self._text
        if key in ("bg", "background"):
            return self._bg
        if key in ("fg", "foreground"):
            return self._fg
        if key == "state":
            return "normal" if self._disabled else "disabled"
        return None


# =========================
# TOAST (feedback não modal)
# =========================
class Toast(QWidget):
    def __init__(self, parent, message, duration=3000):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet(
            "QLabel { background: #1E293B; color: #F8FAFC; border-radius: 10px; padding: 10px 14px; font-size: 13px; }"
        )
        lab = QLabel(message, self)
        lab.setWordWrap(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(lab)
        _shadow(self, blur=30, dy=6)
        self.adjustSize()
        if parent is not None:
            geo = parent.geometry()
            x = geo.x() + max(0, geo.width() - self.width() - 18)
            y = geo.y() + max(0, geo.height() - self.height() - 18)
            self.move(x, y)
        self.show()
        QTimer.singleShot(duration, self.close)

    def closeEvent(self, event):
        if hasattr(self, "app") and self.app is not None:
            self.app._toasts.discard(self)
        super().closeEvent(event)


# =========================
# GRÁFICO QoS
# =========================
class QosGraphWindow(QWidget):
    """Janela leve de gráficos QoS desenhada com QPainter."""

    def __init__(self, app):
        super().__init__(app.main_window())
        self.app = app
        self.setWindowTitle("Estatísticas de QoS")
        self.resize(720, 560)
        self.setMinimumSize(560, 420)
        self.setStyleSheet(_app_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        self.status = QLabel("Sem dados de QoS")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet(f"color:{COLOR_PRIMARY_DARK}; font-weight:700; font-size:14px;")
        root.addWidget(self.status)

        self.canvas = QWidget()
        self.canvas.setStyleSheet(
            f"background:{COLOR_CARD}; border:1px solid {COLOR_BORDER}; border-radius:10px;"
        )
        root.addWidget(self.canvas, 1)

        bar = QHBoxLayout()
        self.btn_export = RoundedButton(self, "Exportar CSV", self.export_csv, COLOR_PRIMARY,
                                        fg="#FFFFFF", pady=5)
        self.btn_export.setMaximumWidth(160)
        bar.addWidget(self.btn_export)
        bar.addStretch(1)
        root.addLayout(bar)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update_draw)
        self._timer.start(1000)

    def canvas_widget(self):
        return self.canvas

    def update_draw(self):
        self.canvas.update()

    def paintEvent(self, event):
        pass

    def paint_canvas(self, painter, width, height):
        metrics = (
            ("Jitter (ms)", "jitter", COLOR_PRIMARY),
            ("Perda (%)", "loss", COLOR_DANGER),
            ("RTT (ms)", "rtt", COLOR_SUCCESS),
        )
        history = self.app.qos_history
        has_data = any(history[key] for _, key, _ in metrics)
        if not has_data:
            painter.setPen(QColor(COLOR_MUTED))
            f = QFont()
            f.setPointSize(11)
            painter.setFont(f)
            painter.drawText(QRectF(0, 0, width, height), Qt.AlignmentFlag.AlignCenter,
                             "Aguardando uma chamada com áudio...")
            self.status.setText("Sem dados de QoS")
            return
        band = max(1, height // len(metrics))
        for index, (title, key, color) in enumerate(metrics):
            top = index * band
            bottom = min(height, top + band - 8)
            values = history[key]
            max_value = max(max(values), 1.0)
            painter.setPen(QColor(COLOR_TEXT))
            bold = QFont()
            bold.setBold(True)
            bold.setPointSize(9)
            painter.setFont(bold)
            painter.drawText(10, top + 12, title)
            painter.setPen(QPen(QColor(COLOR_BORDER), 1))
            painter.drawLine(8, bottom, width - 8, bottom)
            if len(values) < 2:
                continue
            painter.setPen(QPen(QColor(color), 2))
            path = []
            for pos, value in enumerate(values):
                x = 10 + (width - 20) * pos / max(1, len(values) - 1)
                y = bottom - 8 - (bottom - top - 28) * min(value, max_value) / max_value
                path.append((x, y))
            painter.drawPolyline([QPointF(p[0], p[1]) for p in path])
        self._draw_status()

    def _draw_status(self):
        worst = self.app._qos_quality(self.app._latest_qos)
        labels = {"good": "Qualidade excelente", "medium": "Qualidade média", "bad": "Qualidade ruim"}
        colors = {"good": COLOR_SUCCESS, "medium": COLOR_WARNING, "bad": COLOR_DANGER}
        self.status.setText(labels[worst])
        self.status.setStyleSheet(
            f"color:{colors[worst]}; font-weight:700; font-size:14px;"
        )

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar log de QoS", "voice_neves_qos.csv", "CSV (*.csv)"
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
            QMessageBox.critical(self, "QoS", f"Falha ao exportar CSV:\n{e}")

    def closeEvent(self, event):
        self._timer.stop()
        self.app.qos_graph_win = None
        super().closeEvent(event)


# =========================
# SUPORTE EMBUTIR VÍDEO (widget Qt fornece winId)
# =========================
class VideoSurface(QWidget):
    """Área preta que fornece um winId() para o PJSIP embutir o vídeo (X11)."""

    def __init__(self, text="Vídeo desligado", parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setStyleSheet("background:black;")
        self._label = QLabel(text, self)
        self._label.setStyleSheet("color:#888888; background:transparent; font-size:14px;")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def setText(self, text):
        self._text = text

    def get_label(self):
        return self._label

    def set_placeholder(self):
        self._label.setText(self._text)
        self._label.show()
        self._label.setGeometry(self.rect())

    def hide_placeholder(self):
        self._label.hide()

    def resizeEvent(self, event):
        self._label.setGeometry(self.rect())
        super().resizeEvent(event)

    def xid(self):
        return int(self.winId())


# =========================
# DISPATCHER DE THREAD (callbacks pjsua -> main thread)
# =========================
class _UiDispatcher(QObject):
    _sig = Signal(object)


class SoftphoneApp(QMainWindow):
    def __init__(self, app: QApplication):
        super().__init__()
        self.qapp = app
        self.setWindowTitle(APP_NAME)
        _decorate_window(self, maximize=True)
        self.resize(520, 820)
        self.setMinimumSize(460, 760)
        self._base_title = APP_NAME

        self._icon = QIcon(resource_path("Icone.png"))
        self.setWindowIcon(self._icon)

        self._font_name = pick_font()
        self._app_font = QFont(self._font_name)
        self._app_font.setPointSize(10)
        self.setFont(self._app_font)

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
        self._timer_timer = None
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
        self._test_stop_timer = None
        self._answer_blink_on = False
        self._answer_blink_timer = None
        self._blink_color_primary = True
        self.settings_win = None
        self.codec_win = None
        self.edit_win = None
        self._edit_entry = None
        self.adv_win = None
        self.prov_win = None

        self.video_enabled = False
        self._has_video = False
        self.video_win = None
        self.video_surface = None
        self.video_placeholder = None
        self._preview = None
        self._remote_window = None
        self._screen_device_id = -1
        self._screen_shared = False
        self._video_fullscreen = False
        self._mirror_on = False
        self._preview_fit_timer = None
        self.video_bandwidth_spin = None
        self.video_resolution_box = None
        self.video_info_label = None
        self.btn_screen_share = None

        self._main_tid = threading.get_ident()
        self._ui_queue = queue.Queue()
        self._dispatcher = _UiDispatcher()
        self._dispatcher._sig.connect(self._drain_ui_queue)

        self._presence = {}
        self._mwi = {}
        self._presence_buddies = []
        self._forward_timers = {}

        self._tray_icon = None
        self._tray_thread = None
        self._hotkeys = None
        self._theme_proc = None

        self._provisioner = ProvisioningManager(cache_file=prov_cache_path(DATA_DIR))
        self._updater = Updater()
        self._prov_timer = None
        self._prov_thread = None
        self._update_thread = None
        self._last_prov_sync = 0.0
        self._update_checked = False
        self._cti = None

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
            self._font_name = cfg_font
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
        self._toasts = set()

        self._sip_available = pj is not None

        os.environ.setdefault("SDL_VIDEODRIVER", "x11")

        # ---- UI principal ----
        self._build_ui()

        # ---- Ciclo de vida / backends ----
        self.init_pjsip()
        self.apply_saved_codecs()
        self._apply_cached_provision()
        self._start_provision_polling()
        self.auto_register_accounts()
        self.update_call_ui()
        self._setup_tray()
        self._setup_hotkeys()
        self._start_theme_watcher()

        # Timer periódico: esvazia a fila de callbacks e aguenta o pjsua.
        self._loop_timer = QTimer(self)
        self._loop_timer.timeout.connect(self.loop)
        self._loop_timer.start(50)

        QTimer.singleShot(50, self.loop)
        if getattr(self, "_audio_warning", None):
            QTimer.singleShot(1200, self._show_audio_warning)
        _uc = self.config_data.get("updater", {})
        if _uc.get("enabled") and _uc.get("check_on_start", True):
            self._check_updates_async(notify=True)
        self._start_cti()

    def main_window(self):
        return self

    # =========================
    # CONSTRUÇÃO DA UI (Qt)
    # =========================
    def _build_ui(self):
        self.setStyleSheet(_app_qss())
        self._setup_menu_bar()
        self._build_main_area()
        self.load_devices()

    def _setup_menu_bar(self):
        bar = self.menuBar()

        m_arquivo = bar.addMenu("Arquivo")
        a_exp = QAction("Exportar dados...", self)
        a_exp.triggered.connect(self.export_data)
        m_arquivo.addAction(a_exp)
        a_imp = QAction("Importar dados...", self)
        a_imp.triggered.connect(self.import_data)
        m_arquivo.addAction(a_imp)
        m_arquivo.addSeparator()
        a_del = QAction("Deletar Conta", self)
        a_del.setShortcut(QKeySequence("Ctrl+Shift+D"))
        a_del.triggered.connect(self.delete_account)
        m_arquivo.addAction(a_del)
        m_arquivo.addSeparator()
        a_sair = QAction("Sair", self)
        a_sair.setShortcut(QKeySequence("Ctrl+Q"))
        a_sair.triggered.connect(self.close)
        m_arquivo.addAction(a_sair)

        m_editar = bar.addMenu("Editar")
        a_limpar = QAction("Limpar Campos", self)
        a_limpar.triggered.connect(self.clear_fields)
        m_editar.addAction(a_limpar)
        a_redial = QAction("Rediscar", self)
        a_redial.setShortcut(QKeySequence("Ctrl+D"))
        a_redial.triggered.connect(self.redial)
        m_editar.addAction(a_redial)
        a_mute = QAction("Mute/Unmute", self)
        a_mute.triggered.connect(self.toggle_mute)
        m_editar.addAction(a_mute)

        m_config = bar.addMenu("Config.")
        self._config_actions = {}
        for label, fn in (
            ("Configurações...", self.open_settings),
            ("Codecs...", self.open_codecs),
            ("Vídeo...", self.open_video),
            ("Segurança e NAT...", self.open_advanced),
            ("Provisionamento e Atualização...", self.open_provision),
        ):
            a = QAction(label, self)
            a.triggered.connect(fn)
            m_config.addAction(a)

        m_exibir = bar.addMenu("Exibir")
        a_rereg = QAction("Re-registrar Contas", self)
        a_rereg.triggered.connect(self.auto_register_accounts)
        m_exibir.addAction(a_rereg)
        m_exibir.addSeparator()
        self._dark_action = QAction("Tema Escuro", self)
        self._dark_action.setCheckable(True)
        self._dark_action.setChecked(active_theme() == "dark")
        self._dark_action.toggled.connect(self._on_dark_toggled)
        m_exibir.addAction(self._dark_action)
        m_exibir.addSeparator()
        a_contatos_dir = QAction("Diretório de Contatos...", self)
        a_contatos_dir.triggered.connect(self.open_contacts)
        m_exibir.addAction(a_contatos_dir)
        a_novo_ct = QAction("Novo Contato...", self)
        a_novo_ct.triggered.connect(lambda: self.edit_contact(None))
        m_exibir.addAction(a_novo_ct)
        m_exibir.addSeparator()
        a_qos = QAction("Estatísticas de QoS...", self)
        a_qos.triggered.connect(self.open_qos_graph)
        m_exibir.addAction(a_qos)

        m_recursos = bar.addMenu("Rec.")
        a_dnd = QAction("DND (não perturbe)", self)
        a_dnd.triggered.connect(self.dial_dnd)
        m_recursos.addAction(a_dnd)
        a_fwd = QAction("Encaminhar...", self)
        a_fwd.triggered.connect(self.dial_forward)
        m_recursos.addAction(a_fwd)
        a_auto = QAction("Código auto-atender", self)
        a_auto.triggered.connect(self.dial_autoanswer)
        m_recursos.addAction(a_auto)
        m_recursos.addSeparator()
        self._auto_answer_action = QAction("Auto-atender chamadas", self)
        self._auto_answer_action.setCheckable(True)
        self._auto_answer_action.setChecked(self.auto_answer)
        self._auto_answer_action.toggled.connect(self.toggle_auto_answer)
        m_recursos.addAction(self._auto_answer_action)

        m_historico = bar.addMenu("Hist.")
        a_hist = QAction("Ver Histórico", self)
        a_hist.triggered.connect(self.show_history)
        m_historico.addAction(a_hist)
        a_limpar_hist = QAction("Limpar Histórico", self)
        a_limpar_hist.triggered.connect(self.clear_history)
        m_historico.addAction(a_limpar_hist)

        m_ajuda = bar.addMenu("Ajuda")
        a_prob = QAction("Relatar problema...", self)
        a_prob.triggered.connect(self.report_problem)
        m_ajuda.addAction(a_prob)
        a_ideia = QAction("Compartilhar ideia...", self)
        a_ideia.triggered.connect(self.share_idea)
        m_ajuda.addAction(a_ideia)
        m_ajuda.addSeparator()
        a_sobre = QAction("Sobre", self)
        a_sobre.triggered.connect(self.show_about)
        m_ajuda.addAction(a_sobre)

    def _on_dark_toggled(self, checked):
        self.theme_name = "dark" if checked else "light"
        self.config_data["theme"] = self.theme_name
        save_config(self.config_data)
        self.apply_theme(self.theme_name)

    def _header(self):
        header = QWidget()
        header.setStyleSheet(f"background:{COLOR_HEADER};")
        header.setFixedHeight(64)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(16, 0, 14, 0)

        title = QLabel(f"📞  {APP_NAME}")
        title.setStyleSheet("color:#FFFFFF; font-size:16px; font-weight:700; background:transparent;")
        lay.addWidget(title)

        self.timer_label = QLabel("")
        self.timer_label.setStyleSheet(
            "color:#FFFFFF; background:transparent; font-weight:700; font-size:14px;"
        )
        lay.addWidget(self.timer_label)

        self.caller_label = QLabel("")
        self.caller_label.setStyleSheet("color:#FFFFFF; background:transparent; font-weight:700; font-size:14px;")
        lay.addWidget(self.caller_label)

        lay.addStretch(1)

        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color:{STATUS_COLORS['IDLE']}; font-size:18px; background:transparent;")
        self.status_dot.setFixedWidth(22)
        lay.addWidget(self.status_dot)
        self.status_label = QLabel(f"Status: {STATE_LABELS['IDLE']}")
        self.status_label.setStyleSheet("color:#FFFFFF; background:transparent; font-weight:700;")
        lay.addWidget(self.status_label)
        return header

    def _group(self, title, parent_layout):
        g = QGroupBox(title)
        v = QVBoxLayout(g)
        v.setContentsMargins(10, 10, 10, 10)
        parent_layout.addWidget(g)
        return g, v

    def _build_main_area(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._header())

        body = QScrollArea()
        body.setWidgetResizable(True)
        body.setFrameShape(QFrame.Shape.NoFrame)
        body.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        body_widget = QWidget()
        bl = QVBoxLayout(body_widget)
        bl.setContentsMargins(12, 12, 12, 12)
        bl.setSpacing(10)
        body.setWidget(body_widget)
        outer.addWidget(body, 1)

        # --- Contas SIP ---
        acc_group, acc_v = self._group("Contas SIP", bl)
        self.listbox = QListWidget()
        self.listbox.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.listbox.setFixedHeight(72)
        acc_v.addWidget(self.listbox)
        row = QHBoxLayout()
        self.btn_edit = RoundedButton(self, "Editar conta", self.edit_account, COLOR_KEYPAD_BG, COLOR_KEYPAD_FG, pady=5)
        self.btn_delete = RoundedButton(self, "Deletar conta", self.delete_account, COLOR_KEYPAD_BG, COLOR_KEYPAD_FG, pady=5)
        row.addWidget(self.btn_edit)
        row.addWidget(self.btn_delete)
        acc_v.addLayout(row)

        # --- Discagem ---
        dial_group, dial_v = self._group("Discagem", bl)

        num_row = QHBoxLayout()
        num_row.addWidget(QLabel("Número"))
        self.number = QLineEdit()
        self.number.returnPressed.connect(self.make_call)
        num_row.addWidget(self.number, 1)
        dial_v.addLayout(num_row)

        keypad = QGridLayout()
        keypad.setSpacing(4)
        for i, key in enumerate("123456789*0#"):
            r, c = divmod(i, 3)
            btn = RoundedButton(self, key, lambda k=key: self.on_keypad_press(k), COLOR_KEYPAD_BG, COLOR_KEYPAD_FG, pady=6)
            btn.setMinimumHeight(46)
            keypad.addWidget(btn, r, c)
        dial_v.addLayout(keypad)

        feat = QHBoxLayout()
        self.btn_hold = RoundedButton(self, "⏸  Espera", self.toggle_hold, COLOR_KEYPAD_BG, COLOR_KEYPAD_FG, pady=6)
        self.btn_transfer = RoundedButton(self, "↪  Transf.", self.open_transfer, COLOR_KEYPAD_BG, COLOR_KEYPAD_FG, pady=6)
        self.btn_redial = RoundedButton(self, "↺  Rediscar", self.redial, COLOR_KEYPAD_BG, COLOR_KEYPAD_FG, pady=6)
        feat.addWidget(self.btn_hold)
        feat.addWidget(self.btn_transfer)
        feat.addWidget(self.btn_redial)
        dial_v.addLayout(feat)

        self.favorites_frame = QWidget()
        self.favorites_layout = QHBoxLayout(self.favorites_frame)
        self.favorites_layout.setContentsMargins(0, 0, 0, 0)
        dial_v.addWidget(self.favorites_frame)
        self.refresh_favorites()

        call_row = QHBoxLayout()
        self.btn_call = RoundedButton(self, "📞  Ligar", self.make_call, COLOR_KEYPAD_BG, COLOR_KEYPAD_FG, pady=6)
        self.btn_answer = RoundedButton(self, "✅  Atender", self.answer, COLOR_KEYPAD_BG, COLOR_KEYPAD_FG, pady=6)
        call_row.addWidget(self.btn_call)
        call_row.addWidget(self.btn_answer)
        dial_v.addLayout(call_row)

        media_row = QHBoxLayout()
        self.btn_mute = RoundedButton(self, "Mute", self.toggle_mute, COLOR_WARNING, COLOR_TEXT, pady=6)
        self.btn_record = RoundedButton(self, "⏺  Gravar", self.toggle_record, COLOR_KEYPAD_BG, COLOR_KEYPAD_FG, pady=6)
        self.btn_video = RoundedButton(self, "📹  Vídeo", self.toggle_video, COLOR_KEYPAD_BG, COLOR_KEYPAD_FG, pady=6)
        media_row.addWidget(self.btn_mute)
        media_row.addWidget(self.btn_record)
        media_row.addWidget(self.btn_video)
        dial_v.addLayout(media_row)

        # --- Chamadas ativas ---
        active_group, active_v = self._group("Chamadas ativas", bl)
        switch_row = QHBoxLayout()
        self.call_switch_box = QComboBox()
        self.call_switch_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_alternate = RoundedButton(self, "Alternar", self.alternate_call, COLOR_PRIMARY, "#FFFFFF", pady=5)
        switch_row.addWidget(self.call_switch_box, 1)
        switch_row.addWidget(self.btn_alternate)
        active_v.addLayout(switch_row)

        self.qos_label = QLabel("")
        self.qos_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qos_label.setStyleSheet("font-weight:700;")
        active_v.addWidget(self.qos_label)

        self.zrtp_label = QLabel("Cripto: —")
        self.zrtp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zrtp_label.setStyleSheet("font-weight:700;")
        active_v.addWidget(self.zrtp_label)
        self._update_zrtp_ui()

        bl.addStretch(1)

    def _styled_button(self, parent, text, command, color, fg="#FFFFFF", **kw):
        return RoundedButton(parent, text=text, command=command, bg=color, fg=fg, **kw)

    # ---- helpers visuais reutilizáveis ----
    def _info(self, title, text, parent=None):
        QMessageBox.information(parent or self, title, text)

    def _warn(self, title, text, parent=None):
        QMessageBox.warning(parent or self, title, text)

    def _error(self, title, text, parent=None):
        QMessageBox.critical(parent or self, title, text)

    def _ask_yes(self, title, text, parent=None):
        return QMessageBox.question(
            parent or self, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    # =========================
    # MISC UI
    # =========================
    def clear_fields(self):
        self.number.clear()
        if self.settings_win is not None:
            for entry in self._settings_entries():
                if isinstance(entry, QLineEdit):
                    entry.clear()

    def _settings_entries(self):
        for name in ("server", "user", "password", "backup_server"):
            w = getattr(self, name, None)
            if w is not None:
                yield w

    def _contact_feedback(self, subject):
        email = CONTACT_EMAIL
        try:
            webbrowser.open(
                f"mailto:{email}?subject={quote(subject + ' - ' + APP_NAME)}"
            )
        except Exception as e:
            logging.warning("Não foi possível abrir o cliente de e-mail: %s", e)
        self._info(
            "Ajuda",
            f"Para {subject.lower()} sobre o {APP_NAME}, escreva para:\n\n"
            f"  {email}\n\n"
            f"Seu programa de e-mail foi aberto com o assunto preenchido.",
        )

    def report_problem(self):
        self._contact_feedback("Relatar problema")

    def share_idea(self):
        self._contact_feedback("Compartilhar ideia")

    def show_toast(self, message, duration=3000):
        try:
            t = Toast(self, message, duration)
            t.app = self
            self._toasts.add(t)
        except Exception as e:
            logging.debug("Não foi possível exibir toast: %s", e)

    def show_about(self):
        QMessageBox.about(
            self,
            f"Sobre — {APP_NAME}",
            f"<b>📞 {APP_NAME}</b><br><br>"
            f"Softphone SIP leve e seguro para chamadas de voz e vídeo, com "
            f"criptografia SRTP/TLS, conferência de três vias, transferência "
            f"de chamadas, gravação, histórico e agenda de contatos.<br><br>"
            f"<b>Versão:</b> {APP_VERSION}<br>"
            f"<b>Desenvolvedor:</b> {APP_DEV}<br>"
            f"<b>Última atualização:</b> {APP_UPDATED}<br>"
            f"<b>Contato:</b> {CONTACT_EMAIL}<br><br>"
            f"Licença MIT.",
        )

    def _show_audio_warning(self):
        if not getattr(self, "_audio_warning", None):
            return
        logging.warning("Aviso de áudio ao usuário: %s", self._audio_warning)
        self._warn("Problema de áudio detectado", self._audio_warning)
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
            logging.critical("NENHUM dispositivo de áudio PJSIP disponível (0).")
            self._audio_warning = (
                "Nenhum dispositivo de áudio foi encontrado pelo PJSIP.\n"
                "As chamadas vão conectar SEM SOM."
            )
            return

        err = self._try_open_sound(-1, -2)
        if err is None:
            self._has_audio = True
            logging.info("PJSUA abriu o dispositivo padrão de áudio (%d disponíveis)", len(devs))
            return

        logging.warning("Dispositivo de áudio PADRÃO não abriu (%s). Tentando alternativos...", err)

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
                    "Áudio funcionando com dispositivo alternativo: captura=%d, playback=%d",
                    cap_id, play_id,
                )
                return

        try:
            self.endpoint.audDevManager().setNullDev()
        except Exception as e:
            logging.error("Falha ao ativar dispositivo de áudio nulo: %s", e)
        hint = audio_error_hint(last_err)
        self._audio_warning = (
            "Não foi possível abrir nenhum dispositivo de áudio.\n"
            "As chamadas vão conectar SEM SOM.\n\n" + hint + f"\n\nÚltimo erro: {last_err}"
        )
        logging.critical("NENHUM dispositivo de áudio pôde ser aberto. Chamadas ficarão mudas.")

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
            logging.error("Erro ao criar transporte TLS: %s", e)

    # =========================
    # TEMA
    # =========================
    def _start_theme_watcher(self):
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
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                )
                self._theme_proc = proc
                for _line in proc.stdout:
                    self._ui(_changed)
            except Exception:
                pass

        threading.Thread(target=_watch, daemon=True, name="theme-watch").start()

    def toggle_theme(self):
        self.theme_name = "dark" if active_theme() == "light" else "light"
        self.config_data["theme"] = self.theme_name
        save_config(self.config_data)
        self.apply_theme(self.theme_name)

    def apply_theme(self, name=None):
        if name is not None:
            self.theme_name = name
        set_theme(self.theme_name)
        self.setStyleSheet(_app_qss())
        for attr in ("settings_win", "codec_win", "history_win", "edit_win",
                     "contacts_win", "contact_edit_win", "transfer_win"):
            win = getattr(self, attr, None)
            if win is not None:
                try:
                    win.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        self._edit_entry = None
        self._apply_public_colors_refresh()
        self.refresh()
        self.refresh_favorites()
        self.update_call_ui()
        self._update_zrtp_ui()
        if getattr(self, "_dark_action", None) is not None:
            self._dark_action.setChecked(active_theme() == "dark")
        self.show_toast("Tema aplicado")

    def _apply_public_colors_refresh(self):
        pass

    # =========================
    # CONTAS
    # =========================
    def _selected_account_index(self):
        idx = self.listbox.currentRow()
        return idx if idx >= 0 else None

    def selected_account(self):
        idx = self._selected_account_index()
        if idx is not None and idx < len(self.accounts):
            return self.accounts[idx]
        return None

    def edit_account(self):
        if self.call_state != "IDLE":
            self._warn("Chamada em andamento", "Encerre a chamada atual antes de editar uma conta.")
            return
        entry = self.selected_account()
        if entry is None:
            self._info("Nenhuma seleção", "Selecione uma conta na lista.")
            return

        if self.edit_win is not None:
            try:
                self.edit_win.close()
            except Exception:
                pass
        self.edit_win = None

        dlg = QDialog(self)
        dlg.setWindowTitle("Editar conta")
        dlg.resize(480, 460)
        dlg.setMinimumSize(440, 420)
        dlg.setStyleSheet(_app_qss())
        self.edit_win = dlg
        self._edit_entry = entry
        form = QFormLayout(dlg)
        form.setContentsMargins(12, 12, 12, 12)

        old_user = entry["data"]["user"]
        old_server = entry["data"]["server"]

        self.edit_server = QLineEdit(old_server)
        self.edit_user = QLineEdit(old_user)
        self.edit_password = QLineEdit()
        self.edit_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_backup_server = QLineEdit(entry["data"].get("backup_server", ""))
        form.addRow("Servidor", self.edit_server)
        form.addRow("Ramal", self.edit_user)
        form.addRow("Senha", self.edit_password)
        form.addRow("Servidor de backup", self.edit_backup_server)

        fwd = QGroupBox("Encaminhamento")
        fw = QFormLayout(fwd)
        self.edit_forward_unconditional = QLineEdit(entry["data"].get("forward_unconditional", ""))
        self.edit_forward_busy = QLineEdit(entry["data"].get("forward_busy", ""))
        self.edit_forward_no_answer = QLineEdit(entry["data"].get("forward_no_answer", ""))
        stime = QSpinBox()
        stime.setRange(5, 60)
        stime.setValue(int(entry["data"].get("forward_no_answer_timeout", 20)))
        self.edit_forward_no_answer_timeout = stime
        fw.addRow("Incondicional", self.edit_forward_unconditional)
        fw.addRow("Ocupado", self.edit_forward_busy)
        fw.addRow("Sem resposta", self.edit_forward_no_answer)
        fw.addRow("Tempo sem resposta (s)", stime)
        form.addRow(fwd)

        btn_save = RoundedButton(dlg, "💾  Salvar alterações", self.save_edit_account, COLOR_SUCCESS, "#FFFFFF", pady=6)
        btn_close = RoundedButton(dlg, "Fechar", dlg.close, COLOR_PRIMARY, "#FFFFFF", pady=6)
        btn_row = QHBoxLayout()
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_close)
        form.addRow(btn_row)
        dlg.finished.connect(lambda *_: (self.edit_win is not None and setattr(self, "edit_win", None),
                                          setattr(self, "_edit_entry", None)))
        dlg.exec()

    def save_edit_account(self):
        if self.edit_win is None:
            return
        entry = self._edit_entry if self._edit_entry is not None else self.selected_account()
        if entry is None or entry not in self.accounts:
            self._error("Erro", "Conta não encontrada na lista.")
            return

        old_user = entry["data"]["user"]
        old_server = entry["data"]["server"]
        old_key = f"{old_user}@{old_server}"

        user = clean_extension(self.edit_user.text())
        server = self.edit_server.text().strip()
        password = self.edit_password.text()
        backup_server = self.edit_backup_server.text().strip()

        if not is_valid_extension(user):
            self._error("Erro", "Ramal inválido (use apenas letras, números, _ . + -).")
            return
        if not is_valid_server(server):
            self._error("Erro", "Servidor inválido.")
            return
        if backup_server and not is_valid_server(backup_server):
            self._error("Erro", "Servidor de backup inválido.")
            return

        new_key = f"{user}@{server}"
        if new_key != old_key:
            other = next((a for a in self.config_data["accounts"] if _account_key(a) == new_key), None)
            if other is not None:
                self._error("Erro", f"Já existe uma conta com o ramal {user}@{server}.")
                return

        if password:
            secrets.set(new_key, password)
        elif new_key != old_key:
            old_password = secrets.get(old_key, "")
            if old_password:
                secrets.set(new_key, old_password)

        if new_key != old_key:
            secrets.delete(old_key)

        forward_timeout = self.edit_forward_no_answer_timeout.value()
        forward_data = {
            "forward_unconditional": self.edit_forward_unconditional.text().strip(),
            "forward_busy": self.edit_forward_busy.text().strip(),
            "forward_no_answer": self.edit_forward_no_answer.text().strip(),
            "forward_no_answer_timeout": max(5, min(60, forward_timeout)),
        }

        for i, acc_cfg in enumerate(self.config_data["accounts"]):
            if _account_key(acc_cfg) == old_key:
                self.config_data["accounts"][i] = {
                    "user": user, "server": server, "backup_server": backup_server, **forward_data,
                }
                break

        save_config(self.config_data)
        try:
            entry["acc"].delete()
        except Exception as e:
            logging.warning("Erro ao remover conta antiga do pjsip: %s", e)
        self.accounts.remove(entry)

        if self.edit_win is not None:
            self.edit_win.close()
        self.edit_win = None
        self._edit_entry = None
        self.auto_register_accounts()

    def delete_account(self):
        if self.call_state != "IDLE":
            self._warn("Chamada em andamento", "Encerre a chamada atual antes de deletar uma conta.")
            return
        entry = self.selected_account()
        if entry is None:
            self._info("Nenhuma seleção", "Selecione uma conta na lista.")
            return
        user, server = entry["data"]["user"], entry["data"]["server"]
        try:
            entry["acc"].delete()
        except Exception as e:
            logging.warning("Erro ao remover conta do pjsip: %s", e)
        self.accounts.remove(entry)
        self.config_data["accounts"] = [a for a in self.config_data["accounts"]
                                        if not (a["user"] == user and a["server"] == server)]
        secrets.delete(f"{user}@{server}")
        save_config(self.config_data)
        self.refresh()
        self.update_presence()

    def refresh(self):
        """Campo 'Contas SIP': mostra as contas, ou durante/in para chamadas o
        número e o tempo decorrido da chamada no mesmo espaço."""
        if self.call_state in ("INCOMING", "RINGING", "CALLING", "IN_CALL", "HOLD"):
            self._populate_active_call()
        else:
            self._populate_accounts()

    def _populate_accounts(self):
        keep_idx = self.listbox.currentRow()
        self.listbox.clear()
        status_cfg = {
            "ONLINE": (COLOR_SUCCESS, "●", "ONLINE"),
            "REGISTERING": (COLOR_WARNING, "◐", "REGISTRANDO"),
            "OFFLINE": (COLOR_DANGER, "○", "OFFLINE"),
        }
        for i, entry in enumerate(self.accounts):
            status = entry["status"]
            color, icon, label = status_cfg.get(status, (COLOR_MUTED, "○", status))
            suffix = ""
            mwi = self._mwi.get(id(entry))
            if mwi:
                suffix += f"  📩 {int(mwi)}"
            used = entry.get("server_used")
            primary = (entry.get("data") or {}).get("server", "")
            if used and primary and used != primary:
                suffix += f"  ({used})"
            item = QListWidgetItem(f"{icon}  {entry['data']['user']}  ({label}){suffix}")
            item.setForeground(QColor(color))
            self.listbox.addItem(item)
        if keep_idx is not None and 0 <= keep_idx < self.listbox.count():
            self.listbox.setCurrentRow(keep_idx)

    def _active_caller_display(self):
        call = self.current_call
        if call is None:
            return "—"
        try:
            remote = call.getInfo().remoteUri
        except Exception:
            remote = ""
        contact = self._find_contact_by_number(remote)
        if contact:
            return contact["name"]
        num = self._dialable_from_uri(remote)
        return num or "desconhecido"

    def _populate_active_call(self):
        self._call_box_timer_item = None
        self.listbox.clear()
        caller = self._active_caller_display()
        state = self.call_state
        if state in ("IN_CALL", "HOLD"):
            color = STATUS_COLORS.get(state, COLOR_PRIMARY)
            item = QListWidgetItem(f"📞  {caller}")
            item.setForeground(QColor(color))
            self.listbox.addItem(item)
            timer_item = QListWidgetItem("")
            timer_item.setForeground(QColor(COLOR_TEXT))
            self.listbox.addItem(timer_item)
            self._call_box_timer_item = timer_item
            self._update_active_call_timer()
        else:
            status_text = {
                "INCOMING": "Chamada recebida...",
                "RINGING": "Tocando...",
                "CALLING": "Chamando...",
            }.get(state, "")
            color = STATUS_COLORS.get(state, COLOR_PRIMARY)
            item = QListWidgetItem(f"📞  {caller}  ·  {status_text}".strip())
            item.setForeground(QColor(color))
            self.listbox.addItem(item)

    def _format_call_time(self, start):
        elapsed = max(0, int(time.time() - start))
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _update_active_call_timer(self):
        if getattr(self, "_call_box_timer_item", None) is None:
            return
        call = self.current_call
        start = None
        if call is not None:
            try:
                start = self._call_started.get(call.getId())
            except Exception:
                start = None
        if start is None:
            self._call_box_timer_item.setText("")
            return
        self._call_box_timer_item.setText(f"⏱  {self._format_call_time(start)}")

    def load_devices(self):
        if self.endpoint is None:
            return
        try:
            devs = self.endpoint.audDevManager().enumDev2()
        except Exception as e:
            logging.error("Erro ao listar dispositivos: %s", e)
            return
        ins, outs = [], []
        for index, d in enumerate(devs):
            if d.inputCount:
                ins.append(f"{index} | {d.name}")
            if d.outputCount:
                outs.append(f"{index} | {d.name}")
        if self.settings_win is not None:
            self.input_devices.clear()
            self.input_devices.addItems(ins)
            self.output_devices.clear()
            self.output_devices.addItems(outs)
        if self.video_win is not None:
            cams = []
            try:
                vdevs = self.endpoint.vidDevManager().enumDev2()
                for index, d in enumerate(vdevs):
                    if d.dir & pj.PJMEDIA_DIR_CAPTURE:
                        cams.append(f"{index} | {d.name}")
            except Exception as e:
                logging.error("Erro ao listar câmeras: %s", e)
            self.video_devices.clear()
            self.video_devices.addItems(cams)
            saved = (self.config_data.get("video") or {}).get("device", -1)
            for label in cams:
                if label.startswith(f"{saved} | "):
                    self.video_devices.setCurrentText(label)
                    break
            if self.btn_screen_share is not None:
                self.btn_screen_share.set_enabled(self._find_screen_device() >= 0)

    def _selected_camera(self):
        try:
            return int(self.video_devices.currentText().split(" | ")[0])
        except (ValueError, AttributeError):
            return -1

    def auto_register_accounts(self):
        if not self._sip_available:
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

    FAILOVER_COOLDOWN = 30

    def register_account(self, data, current_server=None):
        user = data["user"]
        server = data.get("server") or ""
        active = str(current_server or server)

        acfg = pj.AccountConfig()
        acfg.idUri = f"sip:{user}@{server}"
        acfg.regConfig.registrarUri = f"sip:{active}"

        self._apply_security_config(acfg)
        self._apply_nat_config(acfg)
        self._apply_video_config(acfg)

        try:
            acfg.mwiConfig.enabled = True
        except Exception as e:
            logging.warning("Não foi possível habilitar MWI: %s", e)

        password = secrets.get(f"{user}@{server}", "")
        cred = pj.AuthCredInfo("digest", "*", user, 0, password)
        acfg.sipConfig.authCreds.append(cred)

        acc = MyAccount(self, data)
        acc.create(acfg)
        if not self.accounts:
            acc.setDefault()

        entry = {
            "acc": acc, "data": dict(data), "server_used": active,
            "status": "REGISTERING", "buddies": [], "_failover_at": 0.0,
        }
        self.accounts.append(entry)
        self._create_presence_buddies(entry)
        return entry

    def _entry_for_account(self, acc):
        for entry in self.accounts:
            if entry["acc"] == acc:
                return entry
        return None

    def _on_account_reg_failed(self, acc):
        entry = self._entry_for_account(acc)
        if entry is not None:
            self._maybe_failover(entry)

    def _maybe_failover(self, entry):
        backup = (entry.get("data") or {}).get("backup_server") or ""
        if not backup:
            return
        now = time.time()
        if now - entry.get("_failover_at", 0) < self.FAILOVER_COOLDOWN:
            return
        entry["_failover_at"] = now
        current = entry.get("server_used") or entry["data"].get("server") or ""
        target = backup if current == (entry["data"].get("server") or "") else (
            entry["data"].get("server") or "")
        server_label = entry["data"].get("server") or ""
        if target and target != current:
            logging.warning("Failover de %s: registrando em %s (estava em %s)",
                            server_label, target, current)
            self._recreate_account(entry, target)
            self.show_toast(f"Servidor indisponível; tentando backup {target}")
        elif current == target:
            logging.info("Failover de %s: backup também indisponível (%s)",
                         entry["data"].get("server"), target)

    def _recreate_account(self, entry, target):
        try:
            idx = self.accounts.index(entry)
        except ValueError:
            idx = -1
        self.accounts.remove(entry)
        try:
            entry["acc"].delete()
        except Exception as e:
            logging.warning("Erro ao remover conta no failover: %s", e)
        for buddy in entry.get("buddies", []):
            try:
                buddy.delete()
            except Exception:
                pass
        self.register_account(entry["data"], current_server=target)
        if idx >= 0 and len(self.accounts) > 1:
            moved = self.accounts.pop()
            self.accounts.insert(min(idx, len(self.accounts)), moved)
        self.refresh()
        self.update_presence()

    def _on_mwi_info(self, acc, count):
        entry = self._entry_for_account(acc)
        if entry is None:
            return
        if count is None:
            self._mwi.pop(id(entry), None)
        else:
            self._mwi[id(entry)] = count
        self.refresh()

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
            text, activity = "Em chamada", pj.PJRPID_ACTIVITY_BUSY
        elif self.call_state in ("CALLING", "RINGING", "INCOMING"):
            text, activity = "Chamando", pj.PJRPID_ACTIVITY_BUSY
        else:
            text, activity = "Disponível", pj.PJRPID_ACTIVITY_UNKNOWN
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
                if sec.get("srtp_tls_only"):
                    try:
                        acfg.mediaConfig.srtpSecureSignaling = pj.PJMEDIA_SRTP_USE_SRTP
                    except AttributeError:
                        acfg.mediaConfig.srtpSecureSignaling = 1
                else:
                    acfg.mediaConfig.srtpSecureSignaling = 0
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

    def save_account(self):
        if self.settings_win is None:
            self._info("Configurações", "Abra Configurações > Contas para adicionar uma conta.")
            return
        user = clean_extension(self.user.text())
        server = self.server.text().strip()
        password = self.password.text()
        backup_server = self.backup_server.text().strip()
        if not is_valid_extension(user):
            self._error("Erro", "Ramal inválido (use apenas letras, números, _ . + -).")
            return
        if not is_valid_server(server):
            self._error("Erro", "Servidor inválido.")
            return
        if backup_server and not is_valid_server(backup_server):
            self._error("Erro", "Servidor de backup inválido.")
            return
        key = f"{user}@{server}"
        existing = next((a for a in self.config_data["accounts"] if _account_key(a) == key), None)
        if password:
            secrets.set(key, password)
        if existing is None:
            self.config_data["accounts"].append({"user": user, "server": server, "backup_server": backup_server})
            save_config(self.config_data)
        for w in (self.user, self.server, self.password, self.backup_server):
            w.clear()
        self.auto_register_accounts()

    # =========================
    # EXPORT / IMPORT
    # =========================
    def export_data(self):
        data = {
            "version": 1,
            "accounts": [{"user": a["user"], "server": a["server"]} for a in self.config_data.get("accounts", [])],
            "contacts": self.contacts,
        }
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar dados", "voiceneves_backup.json", "Arquivo JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logging.info("Dados exportados para %s", path)
            self._info("Exportar", f"Dados exportados para:\n{path}")
        except OSError as e:
            logging.error("Falha ao exportar dados: %s", e)
            self._error("Exportar", f"Falha ao exportar:\n{e}")

    def import_data(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importar dados", "", "Arquivo JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self._error("Importar", f"Falha ao ler o arquivo:\n{e}")
            return
        if not isinstance(data, dict):
            self._error("Importar", "Formato inválido.")
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
        existing_ct = {(clean_extension(c.get("number", "")), c.get("name", "")) for c in self.contacts}
        for c in data.get("contacts") or []:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "").strip()
            number = clean_extension(c.get("number", ""))
            if not name or not number:
                continue
            if (number, name) in existing_ct:
                continue
            self.contacts.append({
                "name": name, "number": number, "server": str(c.get("server") or "").strip(),
                "favorite": bool(c.get("favorite")), "ringtone": str(c.get("ringtone") or "").strip(),
                "monitor_presence": bool(c.get("monitor_presence")),
            })
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
        self._info("Importar",
                   f"Importação concluída:\n{added_acc} conta(s) e {added_ct} contato(s) adicionados.\n\n"
                   "As senhas das contas não são importadas (ficam no cofre de senhas do sistema).")

    # =========================
    # CHAMADAS
    # =========================
    def on_keypad_press(self, digit):
        if self.current_call is not None and self.call_state == "IN_CALL":
            try:
                self.current_call.dialDtmf(digit)
            except Exception as e:
                logging.error("Erro ao enviar DTMF: %s", e)
            return
        self.number.insert(digit)

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
        self.history.append({
            "ts": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "label": label, "kind": kind, "status": "", "duration": "", "secure": False,
        })
        if len(self.history) > 500:
            self.history = self.history[-500:]
        save_history(self.history)
        if call is not None:
            try:
                call._history_idx = len(self.history) - 1
                call._history_kind = kind
            except Exception:
                pass

    def make_call(self, number=None, server=None):
        if not self._sip_available:
            self._info(
                "Backend SIP indisponível",
                "pjsua2 não está disponível neste sistema.\nPara Linux: instale/compile o pjsua2.",
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
            self._warn("Sem contas", "Adicione e registre uma conta primeiro.")
            return
        number = clean_extension(number if number is not None else self.number.text())
        if not number:
            self._warn("Número inválido", "Informe um número para ligar.")
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
            self._error("Erro", msg)

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
            QTimer.singleShot(1000, lambda: self._auto_answer_if_ringing(call))

    def _auto_answer_if_ringing(self, call):
        if self.auto_answer and self.call_state == "INCOMING" and self.incoming_call is call:
            logging.info("Auto-atendendo chamada recebida")
            self.answer()

    def _redirect_incoming_call(self, call, target_uri, reason):
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
        self.history.append({
            "ts": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "label": f"Entrada de {remote}", "kind": "incoming",
            "status": "", "duration": "", "secure": False,
        })
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
            old_timer.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._forward_no_answer_timeout(call, target_uri))
        timer.start(timeout * 1000)
        self._forward_timers[call_id] = timer

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
                    timer_id.stop()
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
            self._error("Erro", msg)

    def hangup(self):
        if self.recording:
            self._stop_recording()
        call = self.current_call
        self.current_call = None
        self.incoming_call = None
        self.current_audio_media = None
        self.muted = False
        self._set_mute_btn_text()
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
        if ci.state in (pj.PJSIP_INV_STATE_CALLING, pj.PJSIP_INV_STATE_EARLY, pj.PJSIP_INV_STATE_CONFIRMED):
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
            if call is self.current_call:
                self._stop_ringback(reason="chamada atual confirmada")
            if self._pending_xfer is not None and self._pending_xfer.get("dst") is call:
                self._complete_attended_xfer(call)
            elif self.conf_active:
                self._add_leg_to_conference(call)
                for cid in list(self.conf_media):
                    c = self.calls.get(cid)
                    if (c is not None and cid != call.getId() and cid in self.held_calls):
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

    # ---- múltiplas chamadas / espera / transferência ----
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
            if not self._call_is_confirmed(call):
                self._start_ringback()
            self.set_call_state("RINGING")
        self.update_call_ui()

    def _after_call_ended(self, call):
        try:
            call_id = call.getId()
            timer_id = self._forward_timers.pop(call_id, None)
            if timer_id is not None:
                timer_id.stop()
        except Exception:
            pass
        if self.recording:
            self._stop_recording()
        self._finalize_history_entry(call)
        self._forget_call(call)
        self._remove_leg_from_conference(call)
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
            self._set_mute_btn_text()
            self._teardown_video_ui()
            self.set_call_state("IDLE")

    def _finalize_history_entry(self, call):
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
            self._info("Espera", "Durante a conferência use os botões de conferência para gerenciar as pernas.")
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
        self.call_switch_box.clear()
        self.call_switch_box.addItems(labels)
        try:
            if self.current_call is not None:
                cur_id = self.current_call.getId()
                if cur_id in self._switch_call_ids:
                    self.call_switch_box.setCurrentIndex(self._switch_call_ids.index(cur_id))
                else:
                    self.call_switch_box.setCurrentIndex(-1)
            else:
                self.call_switch_box.setCurrentIndex(-1)
        except Exception:
            pass

    def alternate_call(self):
        idx = self.call_switch_box.currentIndex()
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
                self.transfer_win.raise_()
                self.transfer_win.activateWindow()
                return
            except Exception:
                self.transfer_win = None
        dlg = QDialog(self)
        dlg.setWindowTitle("Transferir chamada")
        dlg.resize(380, 160)
        dlg.setStyleSheet(_app_qss())
        self.transfer_win = dlg
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("Ramal/número de destino:"))
        entry = QLineEdit()
        v.addWidget(entry)
        entry.setFocus()
        row = QHBoxLayout()
        b_blind = RoundedButton(dlg, "Cega", lambda: self._blind_transfer(entry.text()), COLOR_PRIMARY, "#FFFFFF", pady=5)
        b_att = RoundedButton(dlg, "Assistida", lambda: self._attended_transfer(entry.text()), COLOR_SUCCESS, "#FFFFFF", pady=5)
        row.addWidget(b_blind)
        row.addWidget(b_att)
        v.addLayout(row)
        entry.returnPressed.connect(lambda: self._blind_transfer(entry.text()))
        dlg.finished.connect(lambda *_: setattr(self, "transfer_win", None))
        dlg.exec()

    def _close_transfer_win(self):
        if self.transfer_win is not None:
            self.transfer_win.close()
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
            self._error("Transferir", f"Falha na transferência: {e}")

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
            self._error("Transferir", f"Falha ao iniciar a transferência: {e}")

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
            self._error("Transferir", f"Falha ao concluir a transferência: {e}")

    # ---- conferência ----
    def _call_audio_media(self, call):
        try:
            ci = call.getInfo()
        except Exception:
            return None
        for mi in ci.media:
            if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
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
            self._warn("Conferência", "É preciso estar em uma chamada ativa para iniciar a conferência.")
            return
        audio = self._call_audio_media(call)
        if audio is None:
            self._warn("Conferência", "A chamada ainda não possui áudio ativo.")
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
            self._error("Conferência", f"Falha ao iniciar a conferência: {e}")

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
            for target in (mic, spk):
                try:
                    audio.stopTransmit(target)
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
        self.number.setText(self.pickup_code)
        self.make_call()

    def redial(self):
        if not self._last_number:
            self._info("Rediscar", "Nenhum número discado ainda.")
            return
        self.number.setText(self._last_number)
        self.make_call()

    def _dial_code(self, code):
        code = (code or "").strip()
        if not code:
            self._info("Recursos", "Nenhum código configurado para este recurso.")
            return
        self.number.setText(code)
        self.make_call()

    def dial_dnd(self):
        self._dial_code(self.dnd_code)

    def dial_forward(self):
        code = (self.forward_code or "").strip()
        if not code:
            self._info("Encaminhar", "Nenhum código de encaminhamento configurado.")
            return
        dest, ok = QInputDialog.getText(self, "Encaminhar", "Número de destino do encaminhamento (vazio = usar só o código):")
        if not ok:
            return
        number = f"{code}{clean_extension(dest or '')}"
        self.number.setText(number)
        self.make_call()

    def toggle_auto_answer(self, checked=None):
        if self._auto_answer_action is not None:
            self.auto_answer = bool(self._auto_answer_action.isChecked())
        else:
            self.auto_answer = not self.auto_answer
        self.config_data["auto_answer"] = self.auto_answer
        save_config(self.config_data)
        logging.info("Auto-atender %s", "ativado" if self.auto_answer else "desativado")

    def dial_autoanswer(self):
        self._dial_code(self.autoanswer_code)

    # ---- mídia ----
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
                if mi.type == pj.PJMEDIA_TYPE_AUDIO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                    med = call.getMedia(mi.index)
                    audio = pj.AudioMedia.typecastFromMedia(med)
                    mic = self.endpoint.audDevManager().getCaptureDevMedia()
                    spk = self.endpoint.audDevManager().getPlaybackDevMedia()
                    if not self.muted:
                        mic.startTransmit(audio)
                    audio.startTransmit(spk)
                    self.current_audio_media = audio
                    self.apply_volumes()
                elif mi.type == pj.PJMEDIA_TYPE_VIDEO and mi.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
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
        if label is None:
            return
        call = call or self.current_call
        if call is None:
            label.setText("")
            return
        try:
            info = call.getInfo()
            for media in info.media:
                if media.type == pj.PJMEDIA_TYPE_VIDEO and media.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                    stream = call.getStreamInfo(media.index)
                    codec = getattr(stream, "codecName", "vídeo") or "vídeo"
                    label.setText(f"Codec: {codec}  •  Resolução: automática  •  FPS: automático")
                    return
        except Exception as e:
            logging.debug("Informações de vídeo indisponíveis: %s", e)
        label.setText("Vídeo aguardando mídia")

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
        surface = self.video_surface
        if surface is None:
            return False
        try:
            surface.hide_placeholder()
            xid = surface.xid()
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
        surface = self.video_surface
        if surface is not None:
            try:
                surface.set_placeholder()
            except Exception:
                pass

    def on_call_media_state(self, call):
        if self.conf_active:
            self._add_leg_to_conference(call)
            if call is self.current_call:
                self._update_zrtp_ui(call)
        elif call is self.current_call:
            self._connect_call_media(call)
            self._update_zrtp_ui(call)
            if self.current_audio_media is not None and not self._call_is_confirmed(call):
                logging.info("Mídia antecipada ativa antes do atendimento; toque local mantido")
        self.update_call_ui()

    def _get_zrtp_state(self, call):
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
        return {"secure": bool(getattr(call, "secure_media", False)),
                "sas": "", "verified": False, "kind": "SRTP"}

    def _update_zrtp_ui(self, call=None):
        call = call or self.current_call
        state = self._get_zrtp_state(call)
        if call is not None:
            try:
                self._zrtp_state[call.getId()] = state
            except Exception:
                pass
        label = self.zrtp_label
        if label is None:
            return
        if state is not None and state.get("secure"):
            kind = state.get("kind") or "SRTP"
            if kind == "ZRTP":
                suffix = "Verificado" if state.get("verified") else "confirme o SAS"
                text = f"Cripto: 🔒 ZRTP {suffix}"
            else:
                text = "Cripto: 🔒 SRTP ativo"
            label.setText(text)
            label.setStyleSheet(f"font-weight:700; color:{COLOR_SUCCESS};")
            return
        sec = self.config_data.get("security") or {}
        srtp = str(sec.get("srtp") or "disabled")
        if state is not None:
            if srtp == "mandatory":
                label.setText("Cripto: ⚠ SRTP exigido não negociado")
                label.setStyleSheet(f"font-weight:700; color:{COLOR_WARNING};")
            else:
                label.setText("Cripto: 🔓 sem criptografia")
                label.setStyleSheet(f"font-weight:700; color:{COLOR_WARNING};")
            return
        if self.zrtp_available:
            label.setText("ZRTP: disponível")
        elif srtp == "mandatory":
            label.setText("Cripto: SRTP obrigatório")
        elif srtp == "optional":
            label.setText("Cripto: SRTP opcional")
        else:
            label.setText("Cripto: desativada")
        label.setStyleSheet(f"font-weight:700; color:{COLOR_MUTED};")

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
            self.status_label.setText(f"Status: {label}")
            self.status_dot.setStyleSheet(f"color:{STATUS_COLORS.get(state, COLOR_MUTED)}; font-size:18px; background:transparent;")
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
            if self.windowTitle() != self._base_title:
                self.setWindowTitle(self._base_title)
        self._publish_presence()
        if hasattr(self, "listbox"):
            self.refresh()

    def _sync_call_timer(self):
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
            self._stop_call_timer()
            return
        if self._timer_timer is None:
            self._timer_timer = QTimer(self)
            self._timer_timer.timeout.connect(self._update_call_timer)
            self._timer_timer.start(1000)
            self._update_call_timer()

    def _set_timer_text(self, text):
        if not hasattr(self, "timer_label"):
            return
        if text:
            self.timer_label.setText(text)
            self.timer_label.setStyleSheet(
                "color:#FFFFFF; background:transparent; font-weight:700; font-size:14px;"
            )
        else:
            self.timer_label.setText("")

    def _update_call_timer(self):
        call = self.current_call
        start = None
        if call is not None:
            try:
                start = self._call_started.get(call.getId())
            except Exception:
                start = None
        if start is None:
            if self._timer_timer is not None:
                self._timer_timer.stop()
                self._timer_timer = None
            self._set_timer_text("")
            return
        text = self._format_call_time(start)
        self._set_timer_text(text)
        self._update_active_call_timer()
        self._update_qos_label()

    def _stop_call_timer(self):
        if self._timer_timer is not None:
            self._timer_timer.stop()
            self._timer_timer = None
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
                pkt = self._qos_number(rtcp.rxStat.pkt)
                lost = self._qos_number(rtcp.rxStat.loss)
                total = pkt + lost
                loss_pct = round(lost * 100.0 / total, 1) if total > 0 else 0.0
                return rtt_ms, jitter_ms, loss_pct
        return None

    @staticmethod
    def _qos_number(value):
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
        if label is None:
            return
        try:
            qos = self._read_qos()
        except Exception as e:
            logging.debug("Estatísticas QoS indisponíveis: %s", e)
            qos = None
        if qos is None:
            self._latest_qos = None
            label.setText("")
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
        quality = self._qos_quality(qos)
        color = {"good": COLOR_SUCCESS, "medium": COLOR_WARNING, "bad": COLOR_DANGER}[quality]
        label.setText(
            f"QoS: jitter {jitter_ms:.0f} ms · perda {loss_pct}% · latência (RTT) {rtt_ms:.0f} ms"
        )
        label.setStyleSheet(f"font-weight:700; color:{color};")
        if self.qos_graph_win is not None:
            self.qos_graph_win.update_draw()

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
        if self.qos_graph_win is not None and self.qos_graph_win.isVisible():
            self.qos_graph_win.raise_()
            return
        self.qos_graph_win = QosGraphWindow(self)
        self.qos_graph_win.show()
        self.qos_graph_win.update_draw()

    def update_presence(self):
        if self.call_state != "IDLE":
            return
        if any(entry["status"] == "ONLINE" for entry in self.accounts):
            self.status_label.setText(f"Status: {STATE_LABELS['IDLE']}")
            self.status_dot.setStyleSheet(f"color:{STATUS_COLORS['IDLE']}; font-size:18px; background:transparent;")
        else:
            if not self._sip_available:
                self.status_label.setText("Status: Backend SIP indisponível")
            else:
                self.status_label.setText("Status: Offline")
            self.status_dot.setStyleSheet(f"color:{COLOR_OFFLINE}; font-size:18px; background:transparent;")

    # =========================
    # JANELA CONFIGURAÇÕES (Qt)
    # =========================
    def open_settings(self):
        if self.settings_win is None:
            win = QDialog(self)
            win.setWindowTitle("Configurações")
            _decorate_window(win)
            win.resize(600, 680)
            win.setMinimumSize(520, 540)
            win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            self.settings_win = win
            self._build_settings_ui(win)
            self.load_devices()
        self.settings_win.show()
        self.settings_win.raise_()
        self.settings_win.activateWindow()

    def _close_settings(self):
        if self.settings_win is not None:
            self.settings_win.close()
            self.settings_win = None

    def _make_scroll_tab(self, notebook, title):
        tab = QWidget()
        notebook.addTab(tab, title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(10, 10, 10, 10)
        scroll.setWidget(inner)
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll)
        self._tab_layers[title] = v
        return inner

    def _build_settings_ui(self, win):
        self._tab_layers = {}
        lay = QVBoxLayout(win)
        nb = QTabWidget()
        lay.addWidget(nb)

        tab_contas = self._make_scroll_tab(nb, "Contas")
        tab_audio = self._make_scroll_tab(nb, "Áudio")
        tab_recursos = self._make_scroll_tab(nb, "Recursos")
        tab_ldap = self._make_scroll_tab(nb, "LDAP")
        tab_aparencia = self._make_scroll_tab(nb, "Aparência")

        # ---- Contas ----
        acc_frame = QGroupBox("Adicionar conta")
        tab_contas.layout().addWidget(acc_frame)
        form = QFormLayout(acc_frame)
        self.server = QLineEdit()
        self.server.setPlaceholderText("ex.: 10.0.0.1 ou pbx.empresa.com.br")
        form.addRow("Servidor", self.server)
        self.user = QLineEdit()
        self.user.setPlaceholderText("Número do seu ramal")
        form.addRow("Ramal", self.user)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Senha do ramal (guardada no cofre)")
        form.addRow("Senha", self.password)
        self.btn_save = RoundedButton(self, "💾  Salvar conta", self.save_account, COLOR_SUCCESS,
                                      fg="#FFFFFF", pady=6)
        form.addRow(self.btn_save)

        # ---- Áudio ----
        audio_frame = QGroupBox("Áudio")
        tab_audio.layout().addWidget(audio_frame)
        alam = QFormLayout(audio_frame)
        vol_out_row = QWidget()
        voh = QHBoxLayout(vol_out_row)
        voh.setContentsMargins(0, 0, 0, 0)
        self.vol_out = QSlider(Qt.Orientation.Horizontal)
        self.vol_out.setRange(0, 10)
        self.vol_out.setValue(int(self.volume_out))
        self.vol_out.valueChanged.connect(lambda v: (self.on_volume_out(v), self._update_volume_labels()))
        voh.addWidget(self.vol_out, 1)
        self.vol_out_label = QLabel(str(int(self.volume_out)))
        self.vol_out_label.setFixedWidth(30)
        voh.addWidget(self.vol_out_label)
        alam.addRow("Saída", vol_out_row)
        self.output_devices = QComboBox()
        alam.addRow("Dispositivo de saída", self.output_devices)
        vol_in_row = QWidget()
        vih = QHBoxLayout(vol_in_row)
        vih.setContentsMargins(0, 0, 0, 0)
        self.vol_in = QSlider(Qt.Orientation.Horizontal)
        self.vol_in.setRange(0, 10)
        self.vol_in.setValue(int(self.volume_in))
        self.vol_in.valueChanged.connect(lambda v: (self.on_volume_in(v), self._update_volume_labels()))
        vih.addWidget(self.vol_in, 1)
        self.vol_in_label = QLabel(str(int(self.volume_in)))
        self.vol_in_label.setFixedWidth(30)
        vih.addWidget(self.vol_in_label)
        alam.addRow("Entrada", vol_in_row)
        self.input_devices = QComboBox()
        alam.addRow("Dispositivo de entrada", self.input_devices)
        dev_row = QHBoxLayout()
        self.btn_dev_apply = RoundedButton(self, "Aplicar dispositivos", self.apply_devices, COLOR_PRIMARY,
                                           fg="#FFFFFF", pady=5)
        self.btn_dev_refresh = RoundedButton(self, "Atualizar lista", self.load_devices, COLOR_MUTED,
                                             fg=COLOR_TEXT, pady=5)
        dev_row.addWidget(self.btn_dev_apply)
        dev_row.addWidget(self.btn_dev_refresh)
        alam.addRow(dev_row)

        alam.addRow(QLabel("Toque de chamada"))
        self.ringtone_box = QLineEdit(self._ringtone_display())
        self.ringtone_box.setReadOnly(True)
        alam.addRow(self.ringtone_box)
        ring_btns = QHBoxLayout()
        self.btn_ring_pick = RoundedButton(self, "Procurar...", self._pick_ringtone, COLOR_PRIMARY,
                                           fg="#FFFFFF", pady=5)
        self.btn_ring_test = RoundedButton(self, "Testar", self._test_ringtone, COLOR_MUTED,
                                           fg=COLOR_TEXT, pady=5)
        self.btn_ring_default = RoundedButton(self, "Padrão", self._reset_ringtone, COLOR_MUTED,
                                              fg=COLOR_TEXT, pady=5)
        ring_btns.addWidget(self.btn_ring_pick)
        ring_btns.addWidget(self.btn_ring_test)
        ring_btns.addWidget(self.btn_ring_default)
        alam.addRow(ring_btns)

        # ---- Recursos ----
        feat_frame = QGroupBox("Códigos de feature")
        tab_recursos.layout().addWidget(feat_frame)
        fl = QFormLayout(feat_frame)
        for label, attr in (
            ("Captura (pickup)", "pickup_code"),
            ("Auto-atender (código)", "autoanswer_code"),
            ("DND (não perturbe)", "dnd_code"),
            ("Encaminhar", "forward_code"),
        ):
            entry = QLineEdit(str(getattr(self, attr)))
            setattr(self, f"feat_{attr}", entry)
            fl.addRow(label, entry)
        self.feat_auto_answer = QCheckBox("Atender chamadas automaticamente (auto-answer no app)")
        self.feat_auto_answer.setChecked(self.auto_answer)
        fl.addRow(self.feat_auto_answer)
        self.feat_publish_presence = QCheckBox("Publicar minha presença (online/ocupado)")
        self.feat_publish_presence.setChecked(self.publish_presence)
        fl.addRow(self.feat_publish_presence)
        btn_feat = RoundedButton(self, "💾  Salvar recursos", self._save_feature_codes, COLOR_SUCCESS,
                                 fg="#FFFFFF", pady=6)
        fl.addRow(btn_feat)

        # ---- LDAP ----
        ldap_frame = QGroupBox("LDAP corporativo")
        tab_ldap.layout().addWidget(ldap_frame)
        ll = QFormLayout(ldap_frame)
        ldap_cfg = self.config_data.get("ldap") or {}
        self.ldap_enabled_var = QCheckBox("Ativar agenda corporativa LDAP")
        self.ldap_enabled_var.setChecked(bool(ldap_cfg.get("enabled")))
        ll.addRow(self.ldap_enabled_var)
        for label, key in (
            ("Servidor", "server"), ("Base DN", "base_dn"),
            ("Bind DN", "bind_dn"), ("Filtro", "search_filter"),
        ):
            field = QLineEdit(str(ldap_cfg.get(key, "")))
            setattr(self, f"ldap_{key}_entry", field)
            ll.addRow(label, field)
        self.ldap_bind_password_entry = QLineEdit()
        self.ldap_bind_password_entry.setEchoMode(QLineEdit.EchoMode.Password)
        ll.addRow("Senha bind", self.ldap_bind_password_entry)
        self.ldap_interval_spin = QSpinBox()
        self.ldap_interval_spin.setRange(60, 86400)
        self.ldap_interval_spin.setValue(int(ldap_cfg.get("sync_interval", 3600)))
        ll.addRow("Intervalo (s)", self.ldap_interval_spin)
        ldap_buttons = QHBoxLayout()
        btn_test = RoundedButton(self, "Testar conexão", self.test_ldap, COLOR_PRIMARY, fg="#FFFFFF", pady=5)
        btn_sync = RoundedButton(self, "Sincronizar agora", self.sync_ldap_now, COLOR_MUTED, fg=COLOR_TEXT, pady=5)
        ldap_buttons.addWidget(btn_test)
        ldap_buttons.addWidget(btn_sync)
        ll.addRow(ldap_buttons)

        # ---- Aparência ----
        app_frame = QGroupBox("Aparência")
        tab_aparencia.layout().addWidget(app_frame)
        al = QFormLayout(app_frame)
        theme_box = QWidget()
        th = QHBoxLayout(theme_box)
        th.setContentsMargins(0, 0, 0, 0)
        self._appearance_theme = "auto"
        self._theme_radios = {}
        for value, label in (("auto", "💻 Automático"), ("light", "☀️ Claro"), ("dark", "🌙 Escuro")):
            rb = QRadioButton(label)
            rb.setChecked(self.theme_name == value)
            rb.toggled.connect(lambda checked, v=value: self._apply_appearance_theme(v) if checked else None)
            th.addWidget(rb)
            self._theme_radios[value] = rb
        al.addRow("Tema", theme_box)
        self._appearance_font = QComboBox()
        fams = set(QFontDatabase_families())
        font_values = [f for f in FONT_CANDIDATES if f in fams]
        if self._font_name not in font_values:
            font_values.insert(0, self._font_name)
        self._appearance_font.addItems(font_values)
        self._appearance_font.setCurrentText(self._font_name)
        al.addRow("Fonte da interface", self._appearance_font)
        btn_font = RoundedButton(self, "💾  Aplicar e salvar fonte", self._apply_appearance_font,
                                 COLOR_SUCCESS, fg="#FFFFFF", pady=6)
        al.addRow(btn_font)

        links = QHBoxLayout()
        btn_codecs = RoundedButton(self, "🎵 Codecs", self.open_codecs, COLOR_MUTED, fg=COLOR_TEXT, pady=6)
        btn_video = RoundedButton(self, "📹 Vídeo", self.open_video, COLOR_MUTED, fg=COLOR_TEXT, pady=6)
        btn_adv = RoundedButton(self, "🔒 Segurança e NAT", self.open_advanced, COLOR_MUTED, fg=COLOR_TEXT, pady=6)
        links.addWidget(btn_codecs)
        links.addWidget(btn_video)
        links.addWidget(btn_adv)
        lay.addLayout(links)

    def _apply_appearance_theme(self, value):
        self.theme_name = value
        self.config_data["theme"] = value
        save_config(self.config_data)
        self.apply_theme(value)

    def _apply_appearance_font(self):
        fam = self._appearance_font.currentText()
        self.config_data["font"] = fam
        save_config(self.config_data)
        self._font_name = fam
        self._app_font.setFamily(fam)
        self.setFont(self._app_font)
        self._apply_public_colors_refresh()
        self._info("Aparência", "Fonte aplicada. Reinicie o app para a fonte ter efeito total.")

    def _save_ldap_settings(self):
        try:
            interval = max(60, int(self.ldap_interval_spin.value()))
        except (TypeError, ValueError):
            interval = 3600
        cfg = {
            "enabled": bool(self.ldap_enabled_var.isChecked()),
            "server": self.ldap_server_entry.text().strip(),
            "base_dn": self.ldap_base_dn_entry.text().strip(),
            "bind_dn": self.ldap_bind_dn_entry.text().strip(),
            "search_filter": self.ldap_search_filter_entry.text().strip() or "(objectClass=person)",
            "attributes": (self.config_data.get("ldap") or {}).get("attributes", {}),
            "sync_interval": interval,
            "cache_file": (self.config_data.get("ldap") or {}).get("cache_file", "ldap_cache.json"),
        }
        bind_password = self.ldap_bind_password_entry.text()
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
        self.config_data["pickup_code"] = self.feat_pickup_code.text().strip()
        self.config_data["autoanswer_code"] = self.feat_autoanswer_code.text().strip()
        self.config_data["dnd_code"] = self.feat_dnd_code.text().strip()
        self.config_data["forward_code"] = self.feat_forward_code.text().strip()
        self.config_data["auto_answer"] = bool(self.feat_auto_answer.isChecked())
        self.config_data["publish_presence"] = bool(self.feat_publish_presence.isChecked())
        save_config(self.config_data)
        self.pickup_code = self.config_data["pickup_code"] or "*8"
        self.autoanswer_code = self.config_data["autoanswer_code"]
        self.dnd_code = self.config_data["dnd_code"]
        self.forward_code = self.config_data["forward_code"]
        self.auto_answer = self.config_data["auto_answer"]
        self.publish_presence = self.config_data["publish_presence"]
        if hasattr(self, "_auto_answer_action"):
            self._auto_answer_action.setChecked(self.auto_answer)
        self._info("Recursos", "Códigos de feature salvos.", self.settings_win)

    def _update_volume_labels(self):
        if hasattr(self, "vol_out_label"):
            self.vol_out_label.setText(str(int(self.volume_out)))
        if hasattr(self, "vol_in_label"):
            self.vol_in_label.setText(str(int(self.volume_in)))

    # =========================
    # SEGURANÇA E NAT (avançado)
    # =========================
    def open_advanced(self):
        if self.adv_win is None:
            win = QDialog(self)
            win.setWindowTitle("Segurança e NAT")
            _decorate_window(win)
            win.resize(460, 660)
            win.setMinimumSize(420, 620)
            self.adv_win = win
            self._build_advanced_ui(win)
        self.adv_win.show()
        self.adv_win.raise_()
        self.adv_win.activateWindow()

    def _close_advanced(self):
        if self.adv_win is not None:
            self.adv_win.close()
            self.adv_win = None

    def _build_advanced_ui(self, win):
        container = QWidget()
        lay = QVBoxLayout(container)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(container)
        outer = QVBoxLayout(win)
        outer.addWidget(scroll)

        adv = QGroupBox("Segurança e NAT")
        lay.addWidget(adv)
        form = QFormLayout(adv)
        nat = self.config_data.get("nat") or {}
        sec = self.config_data.get("security") or {}
        srtp_labels = {
            "disabled": "Desabilitado",
            "optional": "Opcional",
            "mandatory": "Obrigatório",
        }

        self.adv_stun = QLineEdit(str(nat.get("stun_server", "")))
        self.adv_stun.setPlaceholderText("ex.: stun.cloudflare.com:3478")
        form.addRow("Servidor STUN", self.adv_stun)
        self.adv_ice = QCheckBox("Habilitar ICE (recomendado com STUN/TURN)")
        self.adv_ice.setChecked(_as_bool(nat.get("ice")))
        form.addRow(self.adv_ice)
        self.adv_turn_enabled = QCheckBox("Habilitar TURN (reencaminhamento de mídia)")
        self.adv_turn_enabled.setChecked(_as_bool(nat.get("turn_enabled")))
        form.addRow(self.adv_turn_enabled)
        self.adv_turn_server = QLineEdit(str(nat.get("turn_server", "")))
        form.addRow("Servidor TURN", self.adv_turn_server)
        self.adv_turn_user = QLineEdit(str(nat.get("turn_user", "")))
        form.addRow("Usuário TURN", self.adv_turn_user)
        self.adv_turn_password = QLineEdit()
        self.adv_turn_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.adv_turn_password.setPlaceholderText("Nova senha TURN (vazio = manter)")
        form.addRow("Senha TURN", self.adv_turn_password)
        self.adv_tls = QCheckBox("Usar TLS (SIPS) nas contas")
        self.adv_tls.setChecked(_as_bool(sec.get("tls")))
        form.addRow(self.adv_tls)
        for label, short, key in (
            ("Arquivo CA (opcional)", "tls_ca", "tls_ca_file"),
            ("Certificado (opcional)", "tls_cert", "tls_cert_file"),
            ("Chave privada (opcional)", "tls_key", "tls_key_file"),
        ):
            row = QWidget()
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 0, 0, 0)
            entry = QLineEdit(str(sec.get(key, "")))
            rh.addWidget(entry, 1)
            btn = RoundedButton(self, "…", lambda e=entry: self._pick_file(e, win),
                                COLOR_MUTED, fg=COLOR_TEXT, pady=2)
            btn.setFixedWidth(34)
            rh.addWidget(btn)
            form.addRow(label, row)
            setattr(self, f"adv_{short}", entry)

        inv = {v: k for k, v in srtp_labels.items()}
        self.adv_srtp = QComboBox()
        self.adv_srtp.addItems([srtp_labels[k] for k in ("disabled", "optional", "mandatory")])
        self.adv_srtp.setCurrentText(inv.get(str(sec.get("srtp") or "disabled"), "Desabilitado"))
        form.addRow("SRTP", self.adv_srtp)
        self.adv_srtp_tls = QCheckBox("SRTP somente com TLS (SIPS)")
        self.adv_srtp_tls.setChecked(_as_bool(sec.get("srtp_tls_only")))
        form.addRow(self.adv_srtp_tls)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        lay.addWidget(sep)

        zrtp_lbl = QLabel("ZRTP (criptografia de mídia ponto a ponto)")
        zrtp_lbl.setStyleSheet(f"font-weight:700; color:{COLOR_PRIMARY_DARK};")
        lay.addWidget(zrtp_lbl)
        self.feat_zrtp_enabled = QCheckBox("Habilitar ZRTP (se disponível no PJSIP)")
        self.feat_zrtp_enabled.setChecked(self.zrtp_config["enabled"])
        lay.addWidget(self.feat_zrtp_enabled)
        self.feat_zrtp_sas = QCheckBox("Exigir confirmação SAS")
        self.feat_zrtp_sas.setChecked(self.zrtp_config["sas_required"])
        lay.addWidget(self.feat_zrtp_sas)
        self.feat_zrtp_allow = QCheckBox("Permitir chamadas sem ZRTP")
        self.feat_zrtp_allow.setChecked(self.zrtp_config["allow_unencrypted"])
        lay.addWidget(self.feat_zrtp_allow)
        zrtp_note = QLabel(
            ("ZRTP ativo no build: %s." % ("sim" if self.zrtp_available else "não"))
            + (" Use o botão 🔒 na chamada para confirmar o SAS." if self.zrtp_available else
               " Recompile o PJSIP com suporte a ZRTP para usar.")
        )
        zrtp_note.setWordWrap(True)
        lay.addWidget(zrtp_note)

        btn_save = RoundedButton(self, "💾  Salvar segurança/NAT", self._save_advanced,
                                 COLOR_SUCCESS, fg="#FFFFFF", pady=6)
        lay.addWidget(btn_save)
        note = QLabel("Alterações de transporte (TLS/STUN/TURN) só valem após reiniciar o app.")
        note.setWordWrap(True)
        lay.addWidget(note)

    def _pick_file(self, entry, parent=None):
        path, _ = QFileDialog.getOpenFileName(
            parent or self,
            "Selecionar arquivo",
            "",
            "Todos os arquivos (*);;Certificado/Chave (*.pem *.crt *.cer *.key)",
        )
        if path:
            entry.setText(path)

    def _save_advanced(self):
        if self.adv_win is None:
            return
        srtp_labels = {
            "Desabilitado": "disabled",
            "Opcional": "optional",
            "Obrigatório": "mandatory",
        }
        sec = {
            "tls": bool(self.adv_tls.isChecked()),
            "tls_ca_file": self.adv_tls_ca.text().strip(),
            "tls_cert_file": self.adv_tls_cert.text().strip(),
            "tls_key_file": self.adv_tls_key.text().strip(),
            "srtp": srtp_labels.get(self.adv_srtp.currentText(), "disabled"),
            "srtp_tls_only": bool(self.adv_srtp_tls.isChecked()),
        }
        turn_pw = self.adv_turn_password.text()
        if turn_pw:
            secrets.set("turn", turn_pw)
        nat = {
            "stun_server": self.adv_stun.text().strip(),
            "ice": bool(self.adv_ice.isChecked()),
            "turn_enabled": bool(self.adv_turn_enabled.isChecked()),
            "turn_server": self.adv_turn_server.text().strip(),
            "turn_user": self.adv_turn_user.text().strip(),
            "turn_password": secrets.get("turn", ""),
        }
        self.config_data["security"] = sec
        self.config_data["nat"] = nat
        self.config_data["zrtp"] = {
            "enabled": bool(self.feat_zrtp_enabled.isChecked()),
            "sas_required": bool(self.feat_zrtp_sas.isChecked()),
            "allow_unencrypted": bool(self.feat_zrtp_allow.isChecked()),
        }
        save_config(self.config_data)
        self.zrtp_config = _clean_zrtp(self.config_data["zrtp"])
        self.zrtp_enabled = self.zrtp_config["enabled"] and self.zrtp_available
        if self.zrtp_config["enabled"] and not self.zrtp_available:
            self.show_toast("ZRTP não está disponível neste build do PJSIP")
        self._info(
            "Segurança e NAT",
            "Configurações salvas.\n\nTLS, STUN, TURN e SRTP nas contas só terão efeito "
            "após reiniciar o aplicativo.",
            self.adv_win,
        )

    # =========================
    # NOTIFICAÇÃO / ÁUDIO / TONS
    # =========================
    def _notify_incoming(self):
        try:
            self.showNormal()
            self.raise_()
            self.activateWindow()
            self.setWindowTitle(f"Chamada recebida! - {self._base_title}")
            QApplication.beep()
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
        path, _ = QFileDialog.getOpenFileName(
            self.settings_win,
            "Escolher toque de chamada (WAV)",
            "",
            "Áudio WAV (*.wav);;Todos os arquivos (*)",
        )
        if not path:
            return
        self.config_data["ringtone"] = path
        save_config(self.config_data)
        self.ringtone_box.setText(os.path.basename(path))
        logging.info("Toque de chamada definido: %s", path)

    def _reset_ringtone(self):
        self.config_data["ringtone"] = ""
        save_config(self.config_data)
        if hasattr(self, "ringtone_box"):
            self.ringtone_box.setText("(padrão)")
        logging.info("Toque de chamada restaurado para o padrão")

    def _stop_test_player(self):
        if self._test_stop_timer is not None:
            try:
                self._test_stop_timer.stop()
            except Exception:
                pass
            self._test_stop_timer = None
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
            self._info("Toque", "Nenhum arquivo de toque disponível.")
            return
        if self.endpoint is None:
            self._info("Toque", "Backend SIP indisponível; use o player do sistema.")
            return
        self._stop_test_player()
        try:
            player = pj.AudioMediaPlayer()
            player.createPlayer(path, pj.PJMEDIA_FILE_NO_LOOP)
            spk = self.endpoint.audDevManager().getPlaybackDevMedia()
            player.startTransmit(spk)
            self._test_player = player
            self._test_stop_timer = QTimer(self)
            self._test_stop_timer.setSingleShot(True)
            self._test_stop_timer.timeout.connect(self._stop_test_player)
            self._test_stop_timer.start(9000)
            logging.info("Testando toque de chamada: %s", path)
        except Exception as e:
            self._info("Erro", f"Não foi possível tocar o arquivo: {e}")
            logging.error("Erro ao testar toque de chamada: %s", e)

    def _make_tone_gen(self, freq, on_msec, off_msec):
        tg = pj.ToneGenerator()
        tg.createToneGenerator(8000)
        desc = pj.ToneDesc()
        desc.freq1 = freq
        desc.freq2 = 0
        desc.on_msec = on_msec
        desc.off_msec = off_msec
        desc.volume = 0
        vec = pj.ToneDescVector()
        vec.push_back(desc)
        tg.play(vec, True)
        return tg

    def _play_tone(self, freq, on_msec, off_msec):
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
                player.createPlayer(moh_path, 0)
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
                player.createPlayer(path, 0)
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
            self.btn_call.setText("⏹  Desligar")
            self.btn_call._command = self.hangup
            self.btn_call.set_color(COLOR_DANGER, "#FFFFFF")
            self.btn_call.set_enabled(True)
        else:
            self.btn_call.setText("📞  Ligar")
            self.btn_call._command = self.make_call
            self.btn_call.set_color(COLOR_KEYPAD_BG, COLOR_KEYPAD_FG)
            self.btn_call.set_enabled(not busy or self.conf_active)
        if self.call_state == "INCOMING":
            self.btn_answer.setText("✅  Atender")
            self.btn_answer._command = self.answer
            self.btn_answer.set_color(COLOR_PRIMARY, "#FFFFFF")
            self.btn_answer.set_enabled(True)
        elif self.conf_active and self.call_state == "IN_CALL":
            self.btn_answer.setText("↩  Sair da conf.")
            self.btn_answer._command = self.exit_conference
            self.btn_answer.set_color(COLOR_DANGER, "#FFFFFF")
            self.btn_answer.set_enabled(True)
        elif self.conf_active:
            self.btn_answer.setText("👥  Conf. ativa")
            self.btn_answer._command = self.exit_conference
            self.btn_answer.set_color(COLOR_KEYPAD_BG, COLOR_KEYPAD_FG)
            self.btn_answer.set_enabled(False)
        elif (
            self.current_call is not None
            and self.call_state == "IN_CALL"
            and self._call_is_confirmed(self.current_call)
        ):
            self.btn_answer.setText("👥  Conferência")
            self.btn_answer._command = self.toggle_conference
            self.btn_answer.set_color(COLOR_KEYPAD_BG, COLOR_KEYPAD_FG)
            self.btn_answer.set_enabled(True)
        else:
            self.btn_answer.setText("✅  Atender")
            self.btn_answer._command = self.answer
            self.btn_answer.set_color(COLOR_KEYPAD_BG, COLOR_KEYPAD_FG)
            self.btn_answer.set_enabled(False)
        self.btn_mute.set_enabled(self.current_audio_media is not None)
        if hasattr(self, "btn_record"):
            self.btn_record.set_enabled(self.current_audio_media is not None)
            self._update_record_btn()
        if hasattr(self, "btn_hold"):
            self.btn_hold.set_enabled(
                self.current_call is not None and self.call_state in ("IN_CALL", "HOLD")
            )
        if hasattr(self, "btn_transfer"):
            self.btn_transfer.set_enabled(
                self.current_call is not None and self.call_state in ("IN_CALL", "HOLD")
            )
        if hasattr(self, "btn_video"):
            self._update_video_btn()
        self.refresh_call_switcher()
        self.refresh()

    def _blink_answer(self, active=None):
        if active is None:
            active = self.call_state == "INCOMING"
        if active:
            if not self._answer_blink_on:
                self._answer_blink_on = True
                self._answer_blink_timer = QTimer(self)
                self._answer_blink_timer.timeout.connect(self._answer_blink_tick)
                self._answer_blink_timer.start(500)
        else:
            self._answer_blink_on = False
            if self._answer_blink_timer is not None:
                try:
                    self._answer_blink_timer.stop()
                except Exception:
                    pass
                self._answer_blink_timer = None
            if hasattr(self, "btn_answer"):
                self.btn_answer.set_color(COLOR_PRIMARY, "#FFFFFF")

    def _answer_blink_tick(self):
        if not getattr(self, "_answer_blink_on", False):
            return
        if self._blink_color_primary:
            self.btn_answer.set_color(COLOR_WARNING, COLOR_TEXT)
            self._blink_color_primary = False
        else:
            self.btn_answer.set_color(COLOR_PRIMARY, "#FFFFFF")
            self._blink_color_primary = True

    # =========================
    # ÁUDIO (volume / mute / gravação)
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
                self._set_mute_btn_text()
                self._publish_presence()
            else:
                mic.stopTransmit(self.current_audio_media)
                self.muted = True
                self._set_mute_btn_text()
        except Exception as e:
            logging.error("Erro no mute: %s", e)

    def _set_mute_btn_text(self):
        if hasattr(self, "btn_mute"):
            self.btn_mute.setText("Unmute" if self.muted else "Mute")

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
            self._warn("Gravar", "Nenhuma chamada ativa para gravar.")
            return
        try:
            os.makedirs(self._record_dir(), exist_ok=True)
        except OSError as e:
            logging.error("Falha ao criar diretório de gravação: %s", e)
            self._error("Gravar", f"Não foi possível criar o diretório de gravação:\n{e}")
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
            self._error("Gravar", f"Falha ao iniciar a gravação:\n{e}")
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
            self.btn_record.setText("⏺  Gravando...")
            self.btn_record._command = self.toggle_record
        else:
            self.btn_record.setText("⏺  Gravar")
            self.btn_record._command = self.toggle_record

    # =========================
    # VÍDEO (janela + ações)
    # =========================
    def open_video(self):
        if self.video_win is None:
            win = QDialog(self)
            win.setWindowTitle("Vídeo")
            _decorate_window(win)
            win.resize(560, 860)
            win.setMinimumSize(520, 740)
            self.video_win = win
            self._build_video_ui(win)
            self.load_devices()
        self.video_win.show()
        self.video_win.raise_()
        self.video_win.activateWindow()

    def _close_video(self):
        self._stop_preview()
        if self._remote_window is not None:
            try:
                self._remote_window.hide()
            except Exception:
                pass
            self._remote_window = None
        if self.video_win is not None:
            self.video_win.close()
            self.video_win = None

    def _build_video_ui(self, win):
        lay = QVBoxLayout(win)
        lay.setContentsMargins(10, 10, 10, 10)

        call_group = QGroupBox("Vídeo da chamada")
        lay.addWidget(call_group, 1)
        cv = QVBoxLayout(call_group)
        self.video_surface = VideoSurface("Vídeo desligado")
        self.video_surface.setMinimumHeight(320)
        cv.addWidget(self.video_surface, 1)
        self.video_placeholder = self.video_surface

        toolbar = QHBoxLayout()
        self.btn_screen_share = RoundedButton(self, "🖥  Compartilhar tela", self._toggle_screen_sharing,
                                              COLOR_PRIMARY, fg="#FFFFFF", pady=5)
        btn_full = RoundedButton(self, "Tela cheia", self._toggle_video_fullscreen,
                                 COLOR_MUTED, fg=COLOR_TEXT, pady=5)
        btn_snap = RoundedButton(self, "Tirar foto", self._take_video_snapshot,
                                 COLOR_MUTED, fg=COLOR_TEXT, pady=5)
        toolbar.addWidget(self.btn_screen_share)
        toolbar.addWidget(btn_full)
        toolbar.addWidget(btn_snap)
        cv.addLayout(toolbar)

        cam_group = QGroupBox("Câmera")
        lay.addWidget(cam_group)
        cl = QFormLayout(cam_group)
        self.video_devices = QComboBox()
        cl.addRow("Câmera", self.video_devices)
        cam_btns = QHBoxLayout()
        self.btn_cam_apply = RoundedButton(self, "Aplicar câmera", self.apply_camera,
                                           COLOR_PRIMARY, fg="#FFFFFF", pady=5)
        self.btn_video_preview = RoundedButton(self, "Ver prévia", self._toggle_preview,
                                               COLOR_MUTED, fg=COLOR_TEXT, pady=5)
        self.btn_video_preview_close = RoundedButton(self, "Fechar prévia", self._stop_preview,
                                                     COLOR_MUTED, fg=COLOR_TEXT, pady=5)
        self.btn_video_mirror = RoundedButton(self, "🪞 Espelhar", self._toggle_mirror,
                                              COLOR_MUTED, fg=COLOR_TEXT, pady=5)
        cam_btns.addWidget(self.btn_cam_apply)
        cam_btns.addWidget(self.btn_video_preview)
        cam_btns.addWidget(self.btn_video_preview_close)
        cam_btns.addWidget(self.btn_video_mirror)
        cl.addRow(cam_btns)
        self.video_preview_area = QWidget()
        self.video_preview_area.setStyleSheet(f"background:black; border:1px solid {COLOR_BORDER};")
        self.video_preview_area.setMinimumHeight(200)
        self.video_preview_area.resizeEvent = self._on_preview_area_configure
        self.video_preview_frame = VideoSurface("Prévia desligada")
        self.video_preview_frame.setMinimumHeight(180)
        self.video_preview_frame.setParent(self.video_preview_area)
        pvp = QVBoxLayout(self.video_preview_area)
        pvp.addWidget(self.video_preview_frame, 1, Qt.AlignmentFlag.AlignCenter)
        cl.addRow(self.video_preview_area)

        settings_group = QGroupBox("Qualidade de vídeo")
        lay.addWidget(settings_group)
        sl = QFormLayout(settings_group)
        self.video_resolution_box = QComboBox()
        self.video_resolution_box.addItems(["auto", "640x480", "1280x720", "1920x1080"])
        self.video_resolution_box.setCurrentText(
            (self.config_data.get("video") or {}).get("video_resolution", "auto")
        )
        sl.addRow("Resolução", self.video_resolution_box)
        self.video_bandwidth_spin = QSpinBox()
        self.video_bandwidth_spin.setRange(0, 10000)
        self.video_bandwidth_spin.setSingleStep(64)
        self.video_bandwidth_spin.setValue(
            int((self.config_data.get("video") or {}).get("video_bandwidth", 0))
        )
        sl.addRow("Largura de banda (kbps)", self.video_bandwidth_spin)
        btn_qual = RoundedButton(self, "Aplicar qualidade", self._save_video_settings,
                                 COLOR_PRIMARY, fg="#FFFFFF", pady=5)
        sl.addRow(btn_qual)
        self.video_info_label = QLabel("")
        self.video_info_label.setWordWrap(True)
        sl.addRow(self.video_info_label)

    def toggle_video(self):
        if not self._has_video:
            self._info("Vídeo indisponível", "O pjsua deste sistema não suporta vídeo.")
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
            self.btn_video.setText("📹  Vídeo")
            self.btn_video.set_enabled(False)
            return
        if self.video_enabled:
            self.btn_video.setText("📹  Vídeo ON")
            self.btn_video.set_color(COLOR_SUCCESS, "#FFFFFF")
        else:
            self.btn_video.setText("📹  Vídeo")
            self.btn_video.set_color(COLOR_KEYPAD_BG, COLOR_KEYPAD_FG)
        self.btn_video.set_enabled(True)

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
        if self._video_fullscreen:
            self.video_win.showFullScreen()
        else:
            self.video_win.showNormal()
            self.video_win.raise_()

    def _take_video_snapshot(self):
        self.show_toast("Captura de frame ainda não é exposta pelo pjsua2 desta versão")

    def _save_video_settings(self):
        if self.video_win is None:
            return
        bandwidth = max(0, int(self.video_bandwidth_spin.value()))
        resolution = self.video_resolution_box.currentText() or "auto"
        video = self.config_data.setdefault("video", {})
        video["video_bandwidth"] = bandwidth
        video["video_resolution"] = resolution
        save_config(self.config_data)
        if self.current_call is not None and self.call_state == "IN_CALL":
            self._reinvite_video_device(self._selected_camera())
        self.show_toast("Qualidade de vídeo salva")

    def apply_devices(self):
        if self.settings_win is None:
            self._info("Configurações", "Abra Configurações > Áudio para escolher dispositivos.")
            return
        if self.endpoint is None:
            self._info("Backend SIP", "Backend SIP indisponível neste sistema; nada a aplicar.")
            return
        try:
            adm = self.endpoint.audDevManager()
            sel = self.input_devices.currentText()
            if sel:
                adm.setCaptureDev(int(sel.split(" | ")[0]))
            sel = self.output_devices.currentText()
            if sel:
                adm.setPlaybackDev(int(sel.split(" | ")[0]))
            logging.info("Dispositivos aplicados: entrada=%s saída=%s",
                         self.input_devices.currentText(), self.output_devices.currentText())
        except Exception as e:
            logging.error("Erro ao aplicar dispositivos: %s", e)
            self._error("Erro", f"Falha ao aplicar dispositivos: {e}")

    def apply_camera(self):
        if self.endpoint is None:
            self._info("Câmera", "Backend SIP indisponível neste sistema; câmera inativa.",
                       self.video_win)
            return
        cam = self._selected_camera()
        if cam < 0:
            self._info("Câmera", "Selecione uma câmera na lista acima.", self.video_win)
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
            self._info("Prévia", "Backend SIP indisponível neste sistema; prévia desativada.",
                       self.video_win)
            return
        if self._preview is not None:
            self._stop_preview()
            return
        dev = self._selected_camera()
        if dev < 0:
            self._info("Prévia", "Selecione uma câmera na lista acima.", self.video_win)
            return
        frame = getattr(self, "video_preview_frame", None)
        if frame is None:
            return
        try:
            xid = frame.xid()
            prm = pj.VideoPreviewOpParam()
            prm.show = True
            prm.format.type = pj.PJMEDIA_TYPE_VIDEO
            prm.format.id = pj.PJMEDIA_FORMAT_I420
            prm.format.width = 640
            prm.format.height = 360
            prm.format.fpsNum = 30
            prm.format.fpsDenum = 1
            prm.window = _native_video_handle(xid)
            self._preview = pj.VideoPreview(dev)
            self._preview.start(prm)
            self._mirror_on = bool(self.config_data.get("preview_mirror"))
            if self._mirror_on:
                try:
                    self._preview.getVideoWindow().setMirror(True)
                except Exception:
                    pass
                self.btn_video_mirror.setText("Espelhado ✓")
            else:
                self.btn_video_mirror.setText("🪞 Espelhar")
            self.btn_video_preview.setText("Atual. prévia")
            logging.info("Prévia da câmera %s iniciada", dev)
        except Exception as e:
            self._preview = None
            self._error("Prévia", f"Não foi possível iniciar a prévia da câmera:\n{e}", self.video_win)

    def _on_preview_area_configure(self, event):
        self._fit_preview_area()

    def _fit_preview_area(self):
        frame = getattr(self, "video_preview_frame", None)
        if frame is None:
            return
        if self._preview is not None:
            try:
                win = self._preview.getVideoWindow()
                size = pj.MediaSize()
                size.w = int(frame.width())
                size.h = int(frame.height())
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
            self.btn_video_mirror.setText("Espelhado ✓" if self._mirror_on else "🪞 Espelhar")
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
        if hasattr(self, "video_preview_frame"):
            try:
                self.video_preview_frame.set_placeholder()
            except Exception:
                pass
        if hasattr(self, "btn_video_preview"):
            try:
                self.btn_video_preview.setText("Ver prévia")
                self.btn_video_mirror.setText("🪞 Espelhar")
            except Exception:
                pass
        self._mirror_on = False

    # =========================
    # CODECS
    # =========================
    def open_codecs(self):
        if self.codec_win is None:
            win = QDialog(self)
            win.setWindowTitle("Configurações de Codecs")
            _decorate_window(win)
            win.resize(560, 560)
            win.setMinimumSize(500, 460)
            self.codec_win = win
            self._build_codec_ui(win)
            self.refresh_codec_list()
        self.codec_win.show()
        self.codec_win.raise_()
        self.codec_win.activateWindow()

    def _close_codecs(self):
        if self.codec_win is not None:
            self.codec_win.close()
            self.codec_win = None

    def _build_codec_ui(self, win):
        self._codec_map = {}
        self._codec_tree_selected = None
        lay = QVBoxLayout(win)

        self.audio_tree = QTreeWidget()
        self.audio_tree.setHeaderLabels(("Estado", "Codec", "Prioridade"))
        self.audio_tree.setColumnWidth(0, 100)
        self.audio_tree.setColumnWidth(2, 80)
        self.video_tree = QTreeWidget()
        self.video_tree.setHeaderLabels(("Estado", "Codec", "Prioridade"))
        self.video_tree.setColumnWidth(0, 100)
        self.video_tree.setColumnWidth(2, 80)
        self.audio_tree.itemSelectionChanged.connect(
            lambda: setattr(self, "_codec_tree_selected", self.audio_tree)
        )
        self.video_tree.itemSelectionChanged.connect(
            lambda: setattr(self, "_codec_tree_selected", self.video_tree)
        )

        aud_group = QGroupBox("Áudio")
        av = QVBoxLayout(aud_group)
        av.addWidget(self.audio_tree)
        lay.addWidget(aud_group, 1)
        vid_group = QGroupBox("Vídeo")
        vv = QVBoxLayout(vid_group)
        vv.addWidget(self.video_tree)
        lay.addWidget(vid_group, 1)

        self.codec_note = QLabel("")
        self.codec_note.setWordWrap(True)
        lay.addWidget(self.codec_note)

        btns = QHBoxLayout()
        btn_ena = RoundedButton(self, "Ativar", lambda: self._codec_action("enable"),
                                COLOR_SUCCESS, fg="#FFFFFF", pady=5)
        btn_dis = RoundedButton(self, "Desativar", lambda: self._codec_action("disable"),
                                COLOR_DANGER, fg="#FFFFFF", pady=5)
        btn_up = RoundedButton(self, "Prioridade +", lambda: self._codec_action("up"),
                               COLOR_PRIMARY, fg="#FFFFFF", pady=5)
        btn_down = RoundedButton(self, "Prioridade −", lambda: self._codec_action("down"),
                                 COLOR_PRIMARY, fg="#FFFFFF", pady=5)
        btn_ref = RoundedButton(self, "Atualizar", self.refresh_codec_list,
                                COLOR_MUTED, fg=COLOR_TEXT, pady=5)
        for b in (btn_ena, btn_dis, btn_up, btn_down, btn_ref):
            btns.addWidget(b)
        lay.addLayout(btns)

    def _insert_codec_row(self, tree, codec_id, desc, priority, unavailable=False):
        if unavailable:
            state = "Indisponível"
            prio_text = "—"
            color = COLOR_MUTED
        else:
            state = "Ativo" if (priority or 0) > 0 else "Desativado"
            prio_text = str(priority)
            color = COLOR_DANGER if (priority or 0) <= 0 else None
        label = f"{codec_id}  ({desc})" if desc else codec_id
        item = QTreeWidgetItem((state, label, prio_text))
        if color:
            item.setForeground(0, QColor(color))
            item.setForeground(1, QColor(color))
        tree.addTopLevelItem(item)
        self._codec_map[(id(tree), id(item))] = (codec_id, unavailable)

    def refresh_codec_list(self):
        if self.codec_win is None:
            return
        if self.endpoint is None:
            self.audio_tree.clear()
            self.video_tree.clear()
            self.codec_note.setText(
                "Backend SIP indisponível neste sistema (pjsua2 é Linux-only neste build)."
            )
            return
        for tree, kind, enumerator in (
            (self.audio_tree, "audio", self.endpoint.codecEnum2),
            (self.video_tree, "video", self.endpoint.videoCodecEnum2),
        ):
            tree.clear()
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
                g729_avail = False
                for i in range(tree.topLevelItemCount()):
                    it = tree.topLevelItem(i)
                    if self._codec_map.get((id(tree), id(it)), ("", False))[0].startswith("G729"):
                        g729_avail = True
                if not g729_avail:
                    self._insert_codec_row(tree, G729_CODEC_ID, "G.729 (grátis)", 0, unavailable=True)
                    self.codec_note.setText(
                        "G.729 (grátis) não está compilado neste build do PJSIP. "
                        "Para usá-lo, recompile o PJSIP com suporte ao BCG729 "
                        "(--with-external-bcg729) e refaça o binário."
                    )
                else:
                    self.codec_note.setText("")

    def _selected_codec(self):
        if self.codec_win is None:
            return None
        tree = self._codec_tree_selected
        if tree is None or not tree.selectedItems():
            if self.audio_tree.selectedItems():
                tree = self.audio_tree
            elif self.video_tree.selectedItems():
                tree = self.video_tree
        if tree is None:
            return None
        self._codec_tree_selected = tree
        item = tree.selectedItems()[0]
        return self._codec_map.get((id(tree), id(item)))

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
            self._error("Codec", f"Não foi possível ajustar o codec {codec_id}:\n{e}")
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
            self._info(
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
    # HISTÓRICO
    # =========================
    def show_history(self):
        win = QDialog(self)
        win.setWindowTitle("Histórico de Chamadas")
        _decorate_window(win)
        win.resize(560, 440)
        win.setMinimumSize(480, 340)
        self.history_win = win
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        container = QWidget()
        lay = QVBoxLayout(container)
        self.history_tree = QTreeWidget()
        self.history_tree.setHeaderLabels(("Data/Hora", "Tipo", "Status", "Número/Contato", "Duração", "Segura"))
        self.history_tree.setColumnWidth(0, 130)
        self.history_tree.setColumnWidth(1, 100)
        self.history_tree.setColumnWidth(2, 110)
        self.history_tree.setColumnWidth(3, 200)
        self.history_tree.setColumnWidth(4, 80)
        self.history_tree.setColumnWidth(5, 60)
        lay.addWidget(self.history_tree)
        self.history_tree.itemDoubleClicked.connect(lambda item, col: self._call_history_number())

        for entry in reversed(self.history):
            tipo, numero = self._history_split(entry)
            QTreeWidgetItem(self.history_tree, (
                entry.get("ts", ""),
                tipo,
                entry.get("status") or "—",
                numero,
                entry.get("duration") or "—",
                "🔒" if entry.get("secure") else "—",
            ))

        btn_frame = QHBoxLayout()
        btn_clear = RoundedButton(self, "🗑  Limpar", self._clear_history_ui,
                                  COLOR_DANGER, fg="#FFFFFF", pady=5)
        btn_call = RoundedButton(self, "Ligar", self._call_history_number,
                                 COLOR_SUCCESS, fg="#FFFFFF", pady=5)
        btn_close = RoundedButton(self, "Fechar", self._close_history_win,
                                  COLOR_PRIMARY, fg="#FFFFFF", pady=5)
        btn_frame.addWidget(btn_clear)
        btn_frame.addStretch(1)
        btn_frame.addWidget(btn_call)
        btn_frame.addWidget(btn_close)
        lay.addLayout(btn_frame)

        outer = QVBoxLayout(win)
        outer.addWidget(container)
        win.show()
        win.raise_()
        win.activateWindow()

    @staticmethod
    def _history_split(entry):
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

    def _clear_history_ui(self):
        if not self.history:
            return
        if not self._ask_yes("Limpar Histórico", "Apagar todo o histórico de chamadas?"):
            return
        self.history = []
        save_history(self.history)
        self.history_tree.clear()
        self._close_history_win()

    def clear_history(self):
        if not self.history:
            return
        if not self._ask_yes("Limpar Histórico", "Apagar todo o histórico de chamadas?"):
            return
        self.history = []
        save_history(self.history)

    def _history_selected_number(self):
        tree = getattr(self, "history_tree", None)
        if tree is None:
            return None
        sel = tree.selectedItems()
        if not sel:
            return None
        values = [sel[0].text(i) for i in range(tree.columnCount())]
        if len(values) >= 4:
            num = values[3]
            return num if num and num != "—" else None
        return None

    def _call_history_number(self, tree=None):
        num = self._history_selected_number()
        if num is None:
            self._info("Histórico", "Selecione uma chamada com número para ligar.")
            return
        self._close_history_win()
        number = self._dialable_from_uri(num)
        if not number:
            return
        self.number.setText(number)
        self.make_call(number, None)

    def _close_history_win(self):
        win = getattr(self, "history_win", None)
        if win is not None:
            win.close()
            self.history_win = None

    # =========================
    # CONTATOS / DIRETÓRIO
    # =========================
    def _dialable_from_uri(self, raw):
        s = str(raw or "").strip()
        lt = s.rfind("<")
        gt = s.rfind(">")
        if lt != -1 and gt != -1 and gt > lt:
            s = s[lt + 1:gt].strip()
        else:
            i = s.lower().rfind("sip:")
            if i != -1:
                s = s[i:]
            s = s.strip('"').strip()
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
        frame = getattr(self, "favorites_frame", None)
        if frame is None or not hasattr(self, "favorites_layout"):
            return
        while self.favorites_layout.count():
            item = self.favorites_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        favs = [c for c in self.contacts if c.get("favorite")][:4]
        if not favs:
            lbl = QLabel("⭐ Favoritos: marque contatos para discagem rápida")
            lbl.setStyleSheet(f"color:{COLOR_MUTED}; font-size:11px;")
            self.favorites_layout.addWidget(lbl)
        else:
            for c in favs:
                label = c["name"] if len(c["name"]) <= 14 else c["name"][:13] + "…"
                btn = RoundedButton(
                    self, f"⭐ {label}", lambda ct=c: self.call_contact(ct),
                    COLOR_WARNING, fg=COLOR_TEXT, pady=4,
                )
                self.favorites_layout.addWidget(btn)
                btn.setToolTip(f"Ligar para {c['name']} ({c['number']})")
        btn = RoundedButton(self, "📒 Contatos", self.open_contacts,
                            COLOR_PRIMARY, fg="#FFFFFF", pady=3)
        btn.setToolTip("Abrir diretório de contatos")
        self.favorites_layout.addWidget(btn)

    def call_contact(self, contact):
        if not contact:
            return
        number = clean_extension(contact.get("number", ""))
        if not number:
            self._warn("Contato", "Este contato não possui um ramal/número válido.")
            return
        self.number.setText(number)
        server = contact.get("server") or None
        self._close_contacts_win()
        self.make_call(number, server)

    def open_contacts(self):
        if self.contacts_win is not None:
            self.contacts_win.show()
            self.contacts_win.raise_()
            self.contacts_win.activateWindow()
            return
        win = QDialog(self)
        win.setWindowTitle("Contatos / Diretório")
        _decorate_window(win)
        win.resize(600, 520)
        win.setMinimumSize(520, 420)
        self.contacts_win = win
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        container = QWidget()
        lay = QVBoxLayout(container)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Buscar:"))
        self.contact_search = QLineEdit()
        self.contact_search.textChanged.connect(self._filter_contacts)
        search_row.addWidget(self.contact_search, 1)
        lay.addLayout(search_row)

        self.contact_tree = QTreeWidget()
        self.contact_tree.setHeaderLabels(("★", "Nome", "Ramal/Número", "Servidor", "Presença", "Toque"))
        self.contact_tree.setColumnWidth(0, 40)
        self.contact_tree.setColumnWidth(1, 180)
        self.contact_tree.setColumnWidth(2, 120)
        self.contact_tree.setColumnWidth(3, 150)
        self.contact_tree.setColumnWidth(4, 90)
        self.contact_tree.setColumnWidth(5, 110)
        lay.addWidget(self.contact_tree)
        self.contact_tree.itemDoubleClicked.connect(lambda item, col: self._call_selected_contact())

        btn_frame = QHBoxLayout()
        btn_new = RoundedButton(self, "➕  Novo", lambda: self.edit_contact(None),
                                COLOR_SUCCESS, fg="#FFFFFF", pady=5)
        btn_edit = RoundedButton(self, "✏️  Editar", lambda: self.edit_contact(self._selected_contact()),
                                 COLOR_WARNING, fg=COLOR_TEXT, pady=5)
        btn_del = RoundedButton(self, "🗑  Excluir", lambda: self.delete_contact(self._selected_contact()),
                                COLOR_DANGER, fg="#FFFFFF", pady=5)
        btn_frame.addWidget(btn_new)
        btn_frame.addWidget(btn_edit)
        btn_frame.addWidget(btn_del)
        btn_frame.addStretch(1)
        btn_call = RoundedButton(self, "Ligar", self._call_selected_contact,
                                 COLOR_SUCCESS, fg="#FFFFFF", pady=5)
        btn_close = RoundedButton(self, "Fechar", self._close_contacts_win,
                                  COLOR_PRIMARY, fg="#FFFFFF", pady=5)
        btn_frame.addWidget(btn_call)
        btn_frame.addWidget(btn_close)
        lay.addLayout(btn_frame)

        outer = QVBoxLayout(win)
        outer.addWidget(container)

        self._filtered_contacts = self._directory_contacts()
        self._populate_contacts_tree()
        win.show()
        win.raise_()
        win.activateWindow()

    def _close_contacts_win(self):
        if self.contact_edit_win is not None:
            self.contact_edit_win.close()
            self.contact_edit_win = None
        if self.contacts_win is not None:
            self.contacts_win.close()
            self.contacts_win = None
        self.contact_search = None
        self.contact_tree = None
        self._filtered_contacts = []

    def _selected_contact(self, tree=None):
        tree = tree or getattr(self, "contact_tree", None)
        if tree is None:
            return None
        sel = tree.selectedItems()
        if not sel:
            return None
        idx = int(sel[0].text(0)) if sel[0].text(0).isdigit() else -1
        if 0 <= idx < len(self._filtered_contacts):
            return self._filtered_contacts[idx]
        return None

    def _populate_contacts_tree(self):
        tree = getattr(self, "contact_tree", None)
        if tree is None:
            return
        tree.clear()
        for i, c in enumerate(self._filtered_contacts):
            ring = c.get("ringtone") or ""
            QTreeWidgetItem(tree, (
                str(i),
                c.get("name", ""),
                c.get("number", ""),
                c.get("server", "") or "—",
                self._presence_label(c),
                os.path.basename(ring) if ring else "padrão",
            ))

    def _filter_contacts(self, _text=None):
        q = (self.contact_search.text() if self.contact_search is not None else "").strip()
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

    def _call_selected_contact(self, tree=None):
        contact = self._selected_contact(tree)
        if contact is None:
            self._info("Contatos", "Selecione um contato na lista.")
            return
        self.call_contact(contact)

    def edit_contact(self, contact=None):
        editing = contact is not None
        win = QDialog(self)
        win.setWindowTitle("Editar Contato" if editing else "Novo Contato")
        _decorate_window(win)
        win.resize(460, 360)
        self.contact_edit_win = win
        form = QFormLayout(win)
        values = {}

        e_name = QLineEdit(contact["name"] if editing else "")
        e_name.setPlaceholderText("Nome do contato")
        form.addRow("Nome *", e_name)
        values["name"] = e_name
        e_number = QLineEdit(contact["number"] if editing else "")
        e_number.setPlaceholderText("Ramal/Número")
        form.addRow("Ramal/Número *", e_number)
        values["number"] = e_number
        e_server = QLineEdit(contact.get("server", "") if editing else "")
        e_server.setPlaceholderText("Servidor SIP (opcional)")
        form.addRow("Servidor (opcional)", e_server)
        values["server"] = e_server
        e_fav = QCheckBox("⭐ Favorito (discagem rápida no teclado)")
        e_fav.setChecked(bool(contact.get("favorite")) if editing else False)
        form.addRow(e_fav)
        values["favorite"] = e_fav
        e_mon = QCheckBox("Monitorar presença deste contato")
        e_mon.setChecked(bool(contact.get("monitor_presence")) if editing else False)
        form.addRow(e_mon)
        values["monitor_presence"] = e_mon
        ring_row = QWidget()
        rh = QHBoxLayout(ring_row)
        rh.setContentsMargins(0, 0, 0, 0)
        e_ring = QLineEdit(contact.get("ringtone", "") if editing else "")
        rh.addWidget(e_ring, 1)
        btn_pick = RoundedButton(self, "…", lambda: e_ring.setText(self._pick_ringtone_path(e_ring.text())),
                                 COLOR_MUTED, fg=COLOR_TEXT, pady=2)
        btn_pick.setFixedWidth(34)
        rh.addWidget(btn_pick)
        btn_x = RoundedButton(self, "✕", lambda: e_ring.setText(""),
                              COLOR_MUTED, fg=COLOR_TEXT, pady=2)
        btn_x.setFixedWidth(34)
        rh.addWidget(btn_x)
        form.addRow("Toque (opcional)", ring_row)
        values["ringtone"] = e_ring

        btn_row = QHBoxLayout()
        btn_save = RoundedButton(self, "💾  Salvar", lambda: self._save_contact(contact, values, win),
                                 COLOR_SUCCESS, fg="#FFFFFF", pady=6)
        btn_cancel = RoundedButton(self, "Cancelar", lambda: (win.close(), setattr(self, "contact_edit_win", None)),
                                   COLOR_PRIMARY, fg="#FFFFFF", pady=6)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_cancel)
        form.addRow(btn_row)

        e_name.setFocus()
        win.show()
        win.raise_()
        win.activateWindow()

    def _pick_ringtone_path(self, current):
        path, _ = QFileDialog.getOpenFileName(
            self.contact_edit_win,
            "Escolher toque de chamada (WAV)",
            "",
            "Áudio WAV (*.wav);;Todos os arquivos (*)",
        )
        return path or current

    def _save_contact(self, old, values, win):
        name = values["name"].text().strip()
        number = clean_extension(values["number"].text().strip())
        server_raw = values["server"].text().strip()
        if not name:
            self._warn("Contato", "Informe o nome do contato.")
            return
        if not number:
            self._warn("Contato", "Informe o ramal/número do contato.")
            return
        if server_raw and not is_valid_server(server_raw):
            self._warn("Contato", "Servidor inválido.")
            return
        contact = {
            "name": name,
            "number": number,
            "server": server_raw,
            "favorite": bool(values["favorite"].isChecked()),
            "ringtone": values["ringtone"].text().strip(),
            "monitor_presence": bool(values["monitor_presence"].isChecked()),
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
        win.close()
        self.contact_edit_win = None

    def delete_contact(self, contact=None):
        if contact is None:
            self._info("Contatos", "Selecione um contato na lista.")
            return
        if not self._ask_yes("Excluir Contato", f"Excluir o contato '{contact['name']}'?"):
            return
        if contact in self.contacts:
            self.contacts.remove(contact)
            self.contacts_store.save(self.contacts)
        self.refresh_favorites()
        if self.contacts_win is not None:
            self._filter_contacts()

    # =========================
    # BANDEJA / HOTKEYS
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
            logging.info("Bandeja do sistema ativada")
        except Exception as e:
            self._tray_icon = None
            logging.warning("Não foi possível iniciar a bandeja do sistema: %s", e)

    def _on_minimize(self):
        try:
            if self._tray_icon is not None and self.isMinimized():
                self.hide()
        except Exception as e:
            logging.warning("Falha ao minimizar para a bandeja: %s", e)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self._on_minimize)
        super().changeEvent(event)

    def _show_window(self):
        try:
            self.showNormal()
            self.raise_()
            self.activateWindow()
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
            try:
                from PySide6.QtGui import QShortcut, QKeySequence
                self._hotkey_f9 = QShortcut(QKeySequence("F9"), self)
                self._hotkey_f9.activated.connect(self._answer_guarded)
                self._hotkey_f10 = QShortcut(QKeySequence("F10"), self)
                self._hotkey_f10.activated.connect(self.hangup)
                self._hotkey_f11 = QShortcut(QKeySequence("F11"), self)
                self._hotkey_f11.activated.connect(self.toggle_mute)
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
        if threading.get_ident() == self._main_tid:
            fn(*args)
        else:
            self._ui_queue.put((fn, args))
            try:
                self._dispatcher._sig.emit(None)
            except Exception:
                pass

    def _drain_ui_queue(self, _=None):
        try:
            while True:
                fn, args = self._ui_queue.get_nowait()
                try:
                    fn(*args)
                except Exception as e:
                    logging.error("Erro em callback de UI: %s", e)
        except queue.Empty:
            pass
        except Exception as e:
            logging.error("Falha ao drenar fila de UI: %s", e)

    def loop(self):
        try:
            if self.endpoint:
                self.endpoint.libHandleEvents(50)
        except Exception as e:
            logging.error("Erro no loop pjsip: %s", e)

    def close(self):
        try:
            self._answer_blink_on = False
            if getattr(self, "_theme_proc", None) is not None:
                try:
                    self._theme_proc.terminate()
                except Exception:
                    pass
                self._theme_proc = None
            if self.recording:
                self._stop_recording()
            if self.ldap_manager is not None:
                try:
                    self.ldap_manager.close()
                except Exception:
                    pass
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
            self._stop_cti()
            if self.qos_graph_win is not None:
                try:
                    self.qos_graph_win.close()
                except Exception:
                    pass
                self.qos_graph_win = None
            self._teardown_conference()
            if self.video_win is not None:
                try:
                    self.video_win.close()
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
        try:
            self.qapp.quit()
        except Exception:
            pass

    def closeEvent(self, event):
        self.close()
        event.accept()

    # =========================
    # PROVISIONING / UPDATER / CTI
    # =========================
    def _apply_cached_provision(self):
        try:
            payload = self._provisioner.cached_payload()
        except Exception as e:
            logging.warning("Cache de provisioning indisponível: %s", e)
            return
        if not payload:
            return
        accounts = payload.get("accounts")
        if isinstance(accounts, list):
            existing = {(a.get("user"), a.get("server")) for a in self.config_data.get("accounts", [])}
            added = False
            for acc in accounts:
                if (acc["user"], acc["server"]) in existing:
                    continue
                self.config_data["accounts"].append({"user": acc["user"], "server": acc["server"]})
                added = True
            if added:
                save_config(self.config_data)
        for key in ("security", "nat"):
            if key in payload and isinstance(payload[key], dict):
                self.config_data.setdefault(key, {}).update(payload[key])
        self.config_data.setdefault("updater", {}).setdefault(
            "check_on_start", self.config_data.get("updater", {}).get("check_on_start", True)
        )

    def _start_provision_polling(self):
        pc = (self.config_data.get("provisioning") or {})
        if not pc.get("enabled"):
            return
        try:
            interval = max(60, int(pc.get("sync_interval", 3600)))
        except (TypeError, ValueError):
            interval = 3600
        self._prov_timer = QTimer(self)
        self._prov_timer.timeout.connect(self._sync_provision_once)
        self._prov_timer.start(interval * 1000)
        self._sync_provision_once()

    def _sync_provision_once(self):
        pc = (self.config_data.get("provisioning") or {})
        url = str(pc.get("url") or "").strip()
        if not url:
            return
        if self._prov_thread is not None and self._prov_thread.is_alive():
            return
        auth_user = str(pc.get("auth_user") or "").strip()
        auth_pass = str(pc.get("auth_pass") or secrets.get("provision_auth", "")).strip()

        def worker():
            try:
                payload, changed, from_cache = self._provisioner.sync(
                    url, auth_user=auth_user, auth_pass=auth_pass
                )
                if payload is None:
                    return
                if changed:
                    self._ui(self._apply_fetched_provision, payload)
            except Exception as e:
                logging.warning("Sincronização de provisioning falhou: %s", e)

        self._prov_thread = threading.Thread(target=worker, name="provision", daemon=True)
        self._prov_thread.start()

    def _apply_fetched_provision(self, payload):
        accounts = payload.get("accounts")
        if isinstance(accounts, list):
            desired = {(a["user"], a["server"]): a for a in accounts}
            self.config_data["accounts"] = []
            for key in desired:
                acc = desired[key]
                self.config_data["accounts"].append({"user": acc["user"], "server": acc["server"]})
                if acc.get("password"):
                    secrets.set(f"{acc['user']}@{acc['server']}", acc["password"])
        for key in ("security", "nat"):
            if key in payload and isinstance(payload[key], dict):
                self.config_data[key] = payload[key]
        save_config(self.config_data)
        self.auto_register_accounts()
        self.show_toast("Provisionamento aplicado")

    def _check_updates_async(self, notify=False):
        uc = (self.config_data.get("updater") or {})
        url = str(uc.get("url") or "").strip()
        if not uc.get("enabled") or not url:
            return
        if self._update_thread is not None and self._update_thread.is_alive():
            return
        if self._update_checked:
            return
        self._update_checked = True

        def worker():
            try:
                available = self._updater.check(url, uc.get("auth_user", ""))
                if available:
                    self._ui(self._on_update_available, self._updater.latest)
                elif notify:
                    self._ui(self.show_toast, "Você está na versão mais recente")
            except Exception as e:
                logging.info("Checagem de atualização falhou: %s", e)

        self._update_thread = threading.Thread(target=worker, name="updater", daemon=True)
        self._update_thread.start()

    def _on_update_available(self, info):
        if not self._ask_yes(
            "Atualização disponível",
            f"Existe uma nova versão ({info.get('version')}) do Voice Neves.\n\n"
            "Baixar agora?",
        ):
            return
        def worker():
            try:
                self._updater.download(
                    auth_user=(self.config_data.get("updater") or {}).get("auth_user", "")
                )
                path = self._updater.downloaded_path
                self._ui(self._on_update_downloaded, path)
            except Exception as e:
                logging.error("Falha ao baixar atualização: %s", e)
                self._ui(self._error, "Atualização", f"Falha ao baixar a atualização:\n{e}")
        threading.Thread(target=worker, name="updater-download", daemon=True).start()

    def _on_update_downloaded(self, path):
        self._info(
            "Atualização pronta",
            f"A nova versão foi baixada.\n\n{path}\n\n"
            "Feche o app e substitua o binário, ou execute-o após fechar para aplicar.",
        )

    def open_provision(self):
        if self.prov_win is None:
            win = QDialog(self)
            win.setWindowTitle("Provisionamento e Atualização")
            _decorate_window(win)
            win.resize(520, 560)
            win.setMinimumSize(480, 520)
            self.prov_win = win
            lay = QVBoxLayout(win)

            prov_group = QGroupBox("Auto-provisioning")
            lay.addWidget(prov_group)
            pv = QFormLayout(prov_group)
            pc = (self.config_data.get("provisioning") or {})
            self.prov_enabled = QCheckBox("Habilitar provisioning remoto")
            self.prov_enabled.setChecked(bool(pc.get("enabled")))
            pv.addRow(self.prov_enabled)
            self.prov_url = QLineEdit(str(pc.get("url") or ""))
            self.prov_url.setPlaceholderText("https://servidor/provision.json")
            pv.addRow("URL", self.prov_url)
            self.prov_user = QLineEdit(str(pc.get("auth_user") or ""))
            pv.addRow("Usuário", self.prov_user)
            self.prov_pass = QLineEdit(str(pc.get("auth_pass") or ""))
            self.prov_pass.setEchoMode(QLineEdit.EchoMode.Password)
            pv.addRow("Senha", self.prov_pass)
            self.prov_interval = QSpinBox()
            self.prov_interval.setRange(60, 86400)
            self.prov_interval.setValue(int(pc.get("sync_interval", 3600)))
            pv.addRow("Intervalo (s)", self.prov_interval)

            upd_group = QGroupBox("Atualização automática")
            lay.addWidget(upd_group)
            uv = QFormLayout(upd_group)
            uc = (self.config_data.get("updater") or {})
            self.upd_enabled = QCheckBox("Habilitar checagem de atualização")
            self.upd_enabled.setChecked(bool(uc.get("enabled")))
            uv.addRow(self.upd_enabled)
            self.upd_url = QLineEdit(str(uc.get("url") or ""))
            self.upd_url.setPlaceholderText("https://raw.githubusercontent.com/USER/REPO/master/version.json")
            uv.addRow("URL version.json", self.upd_url)
            self.upd_auth_user = QLineEdit(str(uc.get("auth_user") or ""))
            uv.addRow("Usuário", self.upd_auth_user)
            self.upd_check_start = QCheckBox("Checar atualização ao iniciar")
            self.upd_check_start.setChecked(bool(uc.get("check_on_start", True)))
            uv.addRow(self.upd_check_start)

            cti_group = QGroupBox("API CTI (integração externa)")
            lay.addWidget(cti_group)
            cv = QFormLayout(cti_group)
            cc = (self.config_data.get("cti") or {})
            self.cti_enabled = QCheckBox("Habilitar API CTI REST local")
            self.cti_enabled.setChecked(bool(cc.get("enabled")))
            cv.addRow(self.cti_enabled)
            self.cti_port = QSpinBox()
            self.cti_port.setRange(1, 65535)
            self.cti_port.setValue(int(cc.get("port", 9020)))
            cv.addRow("Porta", self.cti_port)
            self.cti_token = QLineEdit(str(cc.get("token") or ""))
            self.cti_token.setEchoMode(QLineEdit.EchoMode.Password)
            self.cti_token.setPlaceholderText("Token opcional (X-Auth-Token)")
            cv.addRow("Token", self.cti_token)

            btn_save = RoundedButton(self, "💾  Salvar", self._save_provision_settings,
                                     COLOR_SUCCESS, fg="#FFFFFF", pady=6)
            lay.addWidget(btn_save)
        self.prov_win.show()
        self.prov_win.raise_()
        self.prov_win.activateWindow()

    def _save_provision_settings(self):
        if self.prov_win is None:
            return
        self.config_data["provisioning"] = {
            "enabled": bool(self.prov_enabled.isChecked()),
            "url": self.prov_url.text().strip(),
            "auth_user": self.prov_user.text().strip(),
            "auth_pass": self.prov_pass.text().strip() or (self.config_data.get("provisioning") or {}).get("auth_pass", ""),
            "sync_interval": int(self.prov_interval.value()),
        }
        self.config_data["updater"] = {
            "enabled": bool(self.upd_enabled.isChecked()),
            "url": self.upd_url.text().strip(),
            "auth_user": self.upd_auth_user.text().strip(),
            "check_on_start": bool(self.upd_check_start.isChecked()),
        }
        self.config_data["cti"] = {
            "enabled": bool(self.cti_enabled.isChecked()),
            "port": int(self.cti_port.value()),
            "token": self.cti_token.text().strip(),
        }
        save_config(self.config_data)
        self._stop_provision_polling()
        self._start_provision_polling()
        self._stop_cti()
        self._start_cti()
        self._info("Salvo", "Configurações de provisionamento, atualização e CTI salvas.", self.prov_win)

    def _stop_provision_polling(self):
        if self._prov_timer is not None:
            try:
                self._prov_timer.stop()
            except Exception:
                pass
            self._prov_timer = None

    def _start_cti(self):
        cc = (self.config_data.get("cti") or {})
        if not cc.get("enabled"):
            return
        try:
            from .cti_api import CtiServer
            self._cti = CtiServer(self, port=cc.get("port", 9020), token=cc.get("token", ""))
            self._cti.start()
        except Exception as e:
            logging.warning("Não foi possível iniciar a API CTI: %s", e)
            self._cti = None

    def _stop_cti(self):
        if self._cti is not None:
            try:
                self._cti.stop()
            except Exception:
                pass
            self._cti = None

    def cti_invoke(self, fn, *args):
        result = []
        done = threading.Event()

        def wrapper():
            try:
                result.append(fn(*args))
            except Exception as e:
                result.append((False, f"Erro no controlador: {e}"))
            done.set()

        self._ui(wrapper)
        done.wait(5)
        if not done.is_set():
            return (False, "Tempo esgotado aguardando a main thread")
        return result[0]

    def cti_status(self):
        servers = [e.get("server_used") or (e.get("data") or {}).get("server", "") for e in self.accounts]
        current = self.current_call
        number = ""
        try:
            if current is not None:
                number = self._current_call_number()
        except Exception:
            pass
        return {
            "state": self.call_state,
            "muted": bool(self.muted),
            "recording": bool(self.recording),
            "accounts": sum(1 for e in self.accounts if e.get("status") == "ONLINE"),
            "servers": servers,
            "server": servers[0] if servers else "",
            "current_number": number,
        }

    def cti_make_call(self, number, server=None):
        try:
            self.make_call(number, server)
            return (True, "Chamada iniciada")
        except Exception as e:
            logging.error("Erro CTI ao fazer chamada: %s", e)
            return (False, str(e))

    def cti_answer(self):
        try:
            if self.call_state == "INCOMING":
                self.answer()
                return (True, "Chamada atendida")
            return (False, "Nenhuma chamada recebida")
        except Exception as e:
            return (False, str(e))

    def cti_hangup(self):
        try:
            if self.current_call is not None:
                self.hangup()
                return (True, "Chamada encerrada")
            return (False, "Nenhuma chamada ativa")
        except Exception as e:
            return (False, str(e))

    def cti_hold(self):
        try:
            if self.current_call is not None and self.call_state == "IN_CALL":
                self.toggle_hold()
                return (True, "Chamada em espera")
            return (False, "Nenhuma chamada ativa")
        except Exception as e:
            return (False, str(e))

    def cti_unhold(self):
        try:
            if self.current_call is not None and self.call_state == "HOLD":
                self.toggle_hold()
                return (True, "Chamada retomada")
            return (False, "Nenhuma chamada em espera")
        except Exception as e:
            return (False, str(e))
