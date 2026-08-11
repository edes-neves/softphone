# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# pjsua2 é compilado fora do pip e fica como egg no site-packages do sistema.
PJSUA2_EGG = "/usr/local/lib/python3.14/dist-packages/pjsua2-2.14-py3.14-linux-x86_64.egg"
PJSUA2_LIB = "/usr/local/lib"

a = Analysis(
    ['softphone.py'],
    pathex=[PJSUA2_EGG],
    binaries=[
        (os.path.join(PJSUA2_EGG, '_pjsua2.cpython-314-x86_64-linux-gnu.so'), '.'),
        (os.path.join(PJSUA2_LIB, 'libpjsua2.so'), '.'),
    ],
    datas=collect_data_files('keyring') + [('ringtone.wav', '.'), ('Icone.png', '.')],
    hiddenimports=['pjsua2'] + collect_submodules('keyring'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VoiceNeves',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VoiceNeves',
)
