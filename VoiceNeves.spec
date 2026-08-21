# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = [('ringtone.wav', '.'), ('Icone.png', '.'), ('voiceneves.png', '.')]
hiddenimports = ['pjsua2', 'pystray', 'pynput', 'PIL']
datas += collect_data_files('keyring')
hiddenimports += collect_submodules('voice_neves')
hiddenimports += collect_submodules('keyring')


a = Analysis(
    ['softphone.py'],
    pathex=['build/pjsua2_bundle'],
    binaries=[('build/pjsua2_bundle/_pjsua2.cpython-312-x86_64-linux-gnu.so', '.'), ('build/pjsua2_bundle/lib*.so*', '.')],
    datas=datas,
    hiddenimports=hiddenimports,
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
