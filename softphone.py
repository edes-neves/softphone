#!/usr/bin/env python3
"""Lancador fino do Voice Neves.

A aplicacao agora vive no pacote `voice_neves` (modulos). Este arquivo mantem
o nome `softphone.py` para nao quebrar o `VoiceNeves.spec` do PyInstaller e os
fluxos existentes (AppImage, atalhos de desktop).
"""
from voice_neves.__main__ import main

if __name__ == "__main__":
    main()