"""Constantes do aplicativo (caminhos XDG/Win/Mac, regex, versao, codecs)."""
import os
import re

from . import platform

__all__ = [
    "APP_NAME", "APP_VERSION", "APP_DEV", "APP_UPDATED", "CONTACT_EMAIL",
    "MIT_LICENSE", "CONFIG_DIR_NAME",
    "KEYRING_SERVICE", "CONFIG_DIR", "DATA_DIR", "CONFIG_FILE", "SECRETS_FILE",
    "HISTORY_FILE", "CONTACTS_FILE", "LEGACY_CONFIG_FILE", "EXT_RE", "SERVER_RE",
    "RINGTONE_FILE", "STATE_LABELS", "COLOR_OFFLINE",
    "CODEC_PRIO_DISABLED", "CODEC_PRIO_NORMAL", "CODEC_PRIO_BEST",
    "CODEC_PRIO_STEP", "G729_CODEC_ID", "FONT_CANDIDATES",
]

APP_NAME = "Voice Neves"
APP_VERSION = "1.0.1"
APP_DEV = "José Edes Neves"
APP_UPDATED = "08/2026"
CONTACT_EMAIL = "nevestecnologias@gmail.com"
MIT_LICENSE = (
    "MIT License\n\n"
    "Copyright (c) 2026 José Edes Neves / Neves Tecnologia\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a "
    "copy of this software and associated documentation files (the "
    "\"Software\"), to deal in the Software without restriction, including "
    "without limitation the rights to use, copy, modify, merge, publish, "
    "distribute, sublicense, and/or sell copies of the Software, and to "
    "permit persons to whom the Software is furnished to do so, subject to "
    "the following conditions:\n\n"
    "The above copyright notice and this permission notice shall be included "
    "in all copies or substantial portions of the Software.\n\n"
    "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS "
    "OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF "
    "MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. "
    "IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY "
    "CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, "
    "TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE "
    "SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE."
)
CONFIG_DIR_NAME = "softphone"
KEYRING_SERVICE = "softphone"


CONFIG_DIR = platform.config_dir(CONFIG_DIR_NAME)
DATA_DIR = platform.data_dir(CONFIG_DIR_NAME)

CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

SECRETS_FILE = os.path.join(CONFIG_DIR, "secrets.json")

HISTORY_FILE = os.path.join(DATA_DIR, "history.json")

CONTACTS_FILE = os.path.join(DATA_DIR, "contacts.json")
LEGACY_CONFIG_FILE = "sip_config.json"


EXT_RE = re.compile(r"^[0-9A-Za-z_.+\-*#]+$")
SERVER_RE = re.compile(r"^[0-9A-Za-z.-]+(:\d{1,5})?$")


RINGTONE_FILE = "ringtone.wav"



STATE_LABELS = {
    "IDLE": "Disponível",
    "CALLING": "Chamando...",
    "RINGING": "Tocando...",
    "INCOMING": "Chamada recebida!",
    "IN_CALL": "Em chamada",
    "HOLD": "Em espera",
}

# Temas da interface (claro / escuro)

COLOR_OFFLINE = "#5C4033"


CODEC_PRIO_DISABLED = 0
CODEC_PRIO_NORMAL = 128
CODEC_PRIO_BEST = 255
CODEC_PRIO_STEP = 16
G729_CODEC_ID = "G729/8000/1"


FONT_CANDIDATES = ("Inter", "Roboto", "Segoe UI", "Helvetica", "DejaVu Sans", "Noto Sans", "TkDefaultFont")


