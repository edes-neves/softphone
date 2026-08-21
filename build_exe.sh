#!/usr/bin/env bash
# build_exe.sh — Gera o executável VoiceNeves com PyInstaller.
# Uso: ./build_exe.sh
set -Eeuo pipefail

log() { printf '\n\033[1;34m[build_exe]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[ERRO]\033[0m %s\n' "$*" >&2; exit 1; }

cd "$(dirname "$0")"
PY=".venv/bin/python"

[ -x "$PY" ] || err "venv não encontrado em .venv/"

# ---- 1. Pré-requisitos ------------------------------------------------------
command -v patchelf >/dev/null 2>&1 || {
    log "Instalando patchelf (precisa de sudo)..."
    sudo apt install -y patchelf
}
"$PY" -m PyInstaller --version >/dev/null 2>&1 || {
    log "Instalando pyinstaller no venv..."
    "$PY" -m pip install pyinstaller
}

# ---- 2. Bundle do pjsua2: binding + libs juntos, rpath portátil -------------
BUNDLE="build/pjsua2_bundle"
BINDING="_pjsua2.cpython-312-x86_64-linux-gnu.so"

log "Preparando $BUNDLE..."
# Limpa restos de builds antigos (evita misturar libs incompatíveis)
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE"
cp ".venv/lib/python3.12/site-packages/pjsua2.py" "$BUNDLE/"
cp ".venv/lib/python3.12/site-packages/$BINDING" "$BUNDLE/"
cp third_party/pjsip-dist/lib/*.so* "$BUNDLE/"
patchelf --set-rpath '$ORIGIN' "$BUNDLE/$BINDING"

# ---- 3. PyInstaller ---------------------------------------------------------
log "Gerando executável..."
"$PY" -m PyInstaller --clean --noconfirm \
    --name VoiceNeves \
    softphone.py \
    --paths "$BUNDLE" \
    --add-binary "$BUNDLE/$BINDING:." \
    --add-binary "$BUNDLE/lib*.so*:." \
    --add-data "ringtone.wav:." \
    --add-data "Icone.png:." \
    --add-data "voiceneves.png:." \
    --hidden-import pjsua2 \
    --collect-submodules voice_neves \
    --collect-submodules keyring \
    --collect-data keyring \
    --hidden-import pystray \
    --hidden-import pynput \
    --hidden-import PIL

log "Pronto: dist/VoiceNeves/VoiceNeves"
log "Teste: cd dist/VoiceNeves && ./VoiceNeves"

# ---- 3b. Libs de áudio do SISTEMA não vão no pacote -------------------------
# A libasound/libpulse embutidas (do SO onde compilou) conflitam com os
# plugins de áudio do SO de destino (ex.: PipeWire no Ubuntu 24+), deixando
# o app mudo. Cada máquina deve usar a própria pilha de som.
log "Removendo libasound/libpulse do bundle (usam-se as do SO)..."
rm -f dist/VoiceNeves/_internal/libasound* \
      dist/VoiceNeves/_internal/libpulse*

# ---- 4. AppImage ------------------------------------------------------------
APPIMAGETOOL="appimagetool-x86_64.AppImage"
APPDIR="build/AppDir"

[ -f "$APPIMAGETOOL" ] || err "appimagetool não encontrado: $APPIMAGETOOL"
chmod +x "$APPIMAGETOOL"

log "Montando AppDir em $APPDIR..."
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r dist/VoiceNeves/* "$APPDIR/usr/bin/"

cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/VoiceNeves" "$@"
EOF
chmod +x "$APPDIR/AppRun"

[ -f voiceneves.png ] || err "ícone não encontrado: voiceneves.png"
cp voiceneves.png "$APPDIR/voiceneves.png"
ln -sf voiceneves.png "$APPDIR/.DirIcon"

cat > "$APPDIR/VoiceNeves.desktop" << 'EOF'
[Desktop Entry]
Type=Application
Name=Voice Neves
Comment=Softphone SIP Voice Neves
Exec=VoiceNeves
Icon=voiceneves
Terminal=false
Categories=Network;Telephony;
StartupWMClass=Voice Neves
EOF

log "Gerando VoiceNeves-x86_64.AppImage..."
# Instâncias rodando seguram o arquivo ("Text file busy"); encerra antes.
pkill -9 -f 'VoiceNeves' 2>/dev/null || true
sleep 1
rm -f VoiceNeves-x86_64.AppImage
./"$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" VoiceNeves-x86_64.AppImage \
    > /dev/null 2>&1 || err "falha ao gerar o AppImage"

log "Pronto: VoiceNeves-x86_64.AppImage ($(du -h VoiceNeves-x86_64.AppImage | cut -f1))"
