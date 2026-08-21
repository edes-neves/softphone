"""Utilitários dependentes do SO (paths, notificações, dir de Música).

Centraliza o que antes era hardcoded para Linux/XDG/notify-send. No Linux
produz valores idênticos aos originais (mesmo diretório ~/.config/softphone
e ~/.local/share/softphone, mesmo notify-send). No Windows usa APPDATA/
LOCALAPPDATA. No macOS usa ~/Library/Application Support/softphone.

Este módulo é uma folha: só importa stdlib, para não criar dependência
circular com `constants`.
"""
import logging
import os
import subprocess
import sys


def config_dir(app_name):
    """Diretório de configuração por convenção do SO.

    Linux: $XDG_CONFIG_HOME/softphone (default ~/.config/softphone)
    macOS: ~/Library/Application Support/softphone
    Win:   %APPDATA%/softphone
    """
    if sys.platform == "darwin":
        return os.path.join(
            os.path.expanduser("~"), "Library", "Application Support", app_name
        )
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming"
        )
        return os.path.join(base, app_name)
    # Linux e outros: XDG
    return os.path.join(
        os.environ.get(
            "XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")
        ),
        app_name,
    )


def data_dir(app_name):
    """Diretório de dados por convenção do SO.

    Linux: $XDG_DATA_HOME/softphone (default ~/.local/share/softphone)
    macOS: ~/Library/Application Support/softphone (mesma pasta, padrão Apple)
    Win:   %LOCALAPPDATA%/softphone
    """
    if sys.platform == "darwin":
        return os.path.join(
            os.path.expanduser("~"), "Library", "Application Support", app_name
        )
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
        return os.path.join(base, app_name)
    return os.path.join(
        os.environ.get(
            "XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share")
        ),
        app_name,
    )


def music_dir():
    """Diretório de Música do usuário (~/Music em qualquer SO; XDG_MUSIC_HOME no Linux)."""
    env = os.environ.get("XDG_MUSIC_HOME")
    if env:
        p = os.path.expanduser(env)
        if os.path.isabs(p):
            return p
    return os.path.join(os.path.expanduser("~"), "Music")


def notify_send(app_name, title, message, urgency="normal"):
    """Envia uma notificação nativa sem bloquear a UI. Falha silenciosa.

    Linux: notify-send (libnotify). macOS: osascript display notification.
    Windows: sem equivalente stdlib puro; registra no log (toasts exigem
    pywin32/winrt -- fica como gancho futuro).
    """
    if sys.platform == "darwin":
        msg = message.replace('"', '\\"')
        ttl = title.replace('"', '\\"')
        try:
            subprocess.Popen(
                ["osascript", "-e",
                 f'display notification "{msg}" with title "{app_name}" subtitle "{ttl}"'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logging.info("osascript não encontrado; notificações nativas desativadas (macOS)")
        except Exception as e:
            logging.warning("Falha ao enviar notificação nativa: %s", e)
        return

    if os.name == "nt":
        logging.info("Notificação Windows [%s] %s: %s", urgency, title, message)
        return

    # Linux e demais
    try:
        subprocess.Popen(
            ["notify-send", "-a", app_name, "-u", urgency, title, message],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        logging.info("notify-send não encontrado; notificações nativas desativadas")
    except Exception as e:
        logging.warning("Falha ao enviar notificação nativa: %s", e)


def detect_system_theme():
    """Detecta a preferência de tema claro/escuro do sistema.

    Consulta o color-scheme do GNOME (gsettings) e, como fallback, o nome do
    tema GTK. Retorna "dark" ou "light".
    """
    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0:
            if "prefer-dark" in out.stdout:
                return "dark"
            if "prefer-light" in out.stdout or "default" in out.stdout:
                return "light"
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0 and "-dark" in out.stdout.lower().replace("_", "-"):
            return "dark"
    except Exception:
        pass
    return "light"
