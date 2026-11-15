#!/usr/bin/env bash
# Launcher do Flatpak: roda o bundle autossuficiente do PyInstaller (já inclui
# Python + pjsua2/PJSIP). O binário localiza seu próprio _internal, então basta
# executá-lo a partir do diretório instalado.
cd /app/share/voiceneves
exec /app/share/voiceneves/VoiceNeves "$@"
