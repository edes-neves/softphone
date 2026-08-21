"""Testes do módulo platform (paths/notify cross-plataforma).

Objetivo: garantir que Linux continua idêntico ao original (XDG/notify-send)
e que Win/Mac recebem paths por convenção do SO. Roda no Linux real; Win/Mac
são simulados via monkeypatch de sys.platform / os.name.
"""
import os

import pytest

from voice_neves import platform

# ---------------- config_dir ----------------

def test_config_dir_linux_xdg_default(monkeypatch, tmp_path):
    monkeypatch.setattr(platform.sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    p = platform.config_dir("softphone")
    assert p.endswith(".config/softphone")


def test_config_dir_linux_xdg_env(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/cfg")
    assert platform.config_dir("softphone") == "/custom/cfg/softphone"


def test_config_dir_macos(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "darwin")
    p = platform.config_dir("softphone")
    parts = p.split(os.sep)
    assert parts[-2:-1] == ["Application Support"]
    assert parts[-1] == "softphone"


def test_config_dir_windows_appdata(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(platform.os, "name", "nt")
    monkeypatch.setenv("APPDATA", r"C:\Users\foo\AppData\Roaming")
    p = platform.config_dir("softphone")
    assert p == os.path.join(r"C:\Users\foo\AppData\Roaming", "softphone")


def test_config_dir_windows_fallback(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(platform.os, "name", "nt")
    monkeypatch.delenv("APPDATA", raising=False)
    p = platform.config_dir("softphone")
    assert p.endswith(os.path.join("AppData", "Roaming", "softphone"))


# ---------------- data_dir ----------------

def test_data_dir_linux_default(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    p = platform.data_dir("softphone")
    assert p.endswith(os.path.join(".local", "share", "softphone"))


def test_data_dir_macos(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "darwin")
    p = platform.data_dir("softphone")
    assert p.endswith(os.path.join("Application Support", "softphone"))


def test_data_dir_windows_localappdata(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(platform.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\foo\AppData\Local")
    p = platform.data_dir("softphone")
    assert p == os.path.join(r"C:\Users\foo\AppData\Local", "softphone")


# ---------------- music_dir ----------------

def test_music_dir_linux_xdg_env(monkeypatch):
    monkeypatch.setattr(platform.sys, "platform", "linux")
    monkeypatch.setenv("XDG_MUSIC_HOME", "/home/mus")
    assert platform.music_dir() == "/home/mus"


def test_music_dir_default(monkeypatch):
    monkeypatch.delenv("XDG_MUSIC_HOME", raising=False)
    p = platform.music_dir()
    assert p.endswith("Music")


# ---------------- notify_send: dispatch por SO ----------------

def test_notify_send_linux(monkeypatch):
    captured = {}

    class FakePopen:
        def __init__(self, cmd, *args, **kwargs):
            captured["cmd"] = cmd

    monkeypatch.setattr(platform.sys, "platform", "linux")
    monkeypatch.setattr(platform.os, "name", "posix")
    monkeypatch.setattr(platform.subprocess, "Popen", FakePopen)
    platform.notify_send("App", "Título", "msg")
    assert captured["cmd"][0] == "notify-send"
    assert "-a" in captured["cmd"]


def test_notify_send_macos(monkeypatch):
    captured = {}

    class FakePopen:
        def __init__(self, cmd, *args, **kwargs):
            captured["cmd"] = cmd

    monkeypatch.setattr(platform.sys, "platform", "darwin")
    monkeypatch.setattr(platform.subprocess, "Popen", FakePopen)
    platform.notify_send("App", "Tít\"ulo", "m\"sg")
    assert captured["cmd"][0] == "osascript"
    script = captured["cmd"][2]
    assert script.startswith("display notification ")  # forma do AppleScript
    # as caracteres de aspas do título/mensagem são escapados com \"
    assert '\\"' in script


def test_notify_send_windows(monkeypatch, caplog):
    monkeypatch.setattr(platform.sys, "platform", "win32")
    monkeypatch.setattr(platform.os, "name", "nt")
    caplog.set_level("INFO")
    platform.notify_send("App", "T", "msg")
    # Win: loga em vez de chamar subprocess (toast exigiria pywin32/winrt).
    assert any("Notificação Windows" in r.getMessage() for r in caplog.records)


def test_notify_send_linux_missing_binary(monkeypatch, caplog):
    def boom(*a, **kw):
        raise FileNotFoundError

    monkeypatch.setattr(platform.sys, "platform", "linux")
    monkeypatch.setattr(platform.os, "name", "posix")
    monkeypatch.setattr(platform.subprocess, "Popen", boom)
    caplog.set_level("INFO")
    platform.notify_send("App", "T", "msg")
    assert any("notify-send não encontrado" in r.getMessage() for r in caplog.records)


# ---------------- regressão Linux idêntico ao original ----------------

def test_linux_constants_path_unchanged(monkeypatch):
    """Em Linux (sem XDG_* env), os paths devem bater com os do original."""
    monkeypatch.setattr(platform.sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    home = os.path.expanduser("~")
    assert platform.config_dir("softphone") == os.path.join(home, ".config", "softphone")
    assert platform.data_dir("softphone") == os.path.join(home, ".local", "share", "softphone")
