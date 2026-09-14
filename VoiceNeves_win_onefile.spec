# -*- mode: python ; coding: utf-8 -*-
"""
VoiceNeves_win_onefile.spec — Empacota o softphone num UNICO .exe portátil.

Uso:
    pyinstaller VoiceNeves_win_onefile.spec --noconfirm --clean
"""
import os
import sys
import glob
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

_datas = [('ringtone.wav', '.'), ('Icone.png', '.'), ('Icone.ico', '.'), ('voiceneves.png', '.')]
_hiddenimports = ['pjsua2', 'pystray', 'pynput', 'PIL']
_datas += collect_data_files('keyring')
_hiddenimports += collect_submodules('voice_neves')
_hiddenimports += collect_submodules('keyring')

# --- PJSIP Windows artifacts ---
_pjsip_win = os.path.join('third_party', 'pjsip-win')
_pjsip_dist = os.path.join('third_party', 'pjsip-dist')

_binaries = []
_datas_pjsip = []

# Procurar _pjsua2.pyd no build Windows
_pyd_seen = set()
for base in [_pjsip_win, _pjsip_dist]:
    py_dir = os.path.join(base, 'python')
    if os.path.isdir(py_dir):
        for f in glob.glob(os.path.join(py_dir, '_pjsua2*.pyd')):
            if f not in _pyd_seen:
                _pyd_seen.add(f)
                _binaries.append((f, '.'))
        for f in glob.glob(os.path.join(py_dir, '*.py')):
            if f not in _datas:
                _datas.append((f, '.'))
        # DLLs do runtime (SDL2, openh264) ficam na pasta python/ do build
        for f in glob.glob(os.path.join(py_dir, '*.dll')):
            _binaries.append((f, '.'))

    lib_dir = os.path.join(base, 'lib')
    if os.path.isdir(lib_dir):
        for f in glob.glob(os.path.join(lib_dir, '*.dll')):
            _binaries.append((f, '.'))
        for f in glob.glob(os.path.join(lib_dir, '*.pyd')):
            _binaries.append((f, '.'))

# Fallback: procurar na raiz (DLLs copiadas pelo build_pjsip_win.ps1)
for f in glob.glob('*.dll'):
    if 'python' not in f.lower() and 'msvcr' not in f.lower():
        _binaries.append((f, '.'))

a = Analysis(
    ['softphone.py'],
    pathex=[
        os.path.join('third_party', 'pjsip-win', 'python'),
        os.path.join('third_party', 'pjsip-dist'),
        '.',
    ],
    binaries=_binaries,
    datas=_datas + _datas_pjsip,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'linphone',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VoiceNeves',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon='Icone.ico',
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)