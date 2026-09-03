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

# ---- 3c. Autossuficiência do Qt Xcb (impede erro libxcb-cursor no destino) ---
# As libs Qt ficam em _internal/PySide6/Qt/lib com RPATH "$ORIGIN", mas as
# libs xcb (libxcb-cursor.so.0, libX11, libxkbcommon etc.) são coletadas pelo
# PyInstaller na raiz _internal/. Sem um caminho que aponte para lá, o plugin
# xcb depende das libs do SO de DESTINO. Em máquinas sem libxcb-cursor0
# (ex.: Ubuntu 24.04 limpo) o app falha com:
#   "From 6.5.0, xcb-cursor0 or libxcb-cursor0 is needed to load the Qt xcb..."
# Ajusta o RPATH das libs Qt para também apontar para a raiz (_internal),
# tornando o AppImage autossuficiente para video/cursor.
QT_LIB="dist/VoiceNeves/_internal/PySide6/Qt/lib"
log "Tornando as libs Qt autossuficientes (rpath += \$ORIGIN/../..)..."
if [ -d "$QT_LIB" ]; then
    for f in "$QT_LIB"/libQt6*.so.6; do
        rp="$(patchelf --print-rpath "$f" 2>/dev/null || true)"
        case "$rp" in
            *'$ORIGIN/../..'*) ;;                       # já ajustado
            *'$ORIGIN'*)
                patchelf --set-rpath "$rp:$(printf '%s\n' '$ORIGIN/../..')" "$f" ;;
            *)
                patchelf --set-rpath "$(printf '%s\n' '$ORIGIN:$ORIGIN/../..')" "$f" ;;
        esac
    done
    # libxcb.so.1 foi renomeada pelo PyInstaller para libxcb-ad31f5a3.so.1.1.0
    # (em pillow.libs/); cria o soname clássico na raiz para as libs Qt xcb.
    root_internal="dist/VoiceNeves/_internal"
    if [ -L "$root_internal/libxcb-ad31f5a3.so.1.1.0" ] && [ ! -e "$root_internal/libxcb.so.1" ]; then
        ln -s "libxcb-ad31f5a3.so.1.1.0" "$root_internal/libxcb.so.1"
        log "Criado symlink raiz libxcb.so.1"
    fi

    # Fail-safe: injeta explicitamente as libs xcb do SO na raiz _internal/.
    # O PyInstaller só coleta a libxcb-cursor se o pacote libxcb-cursor0
    # estiver instalado DURANTE o build (é o caso da CI após a instalação).
    # Este bloco garante presença das libs de cursor/video/xkb mesmo que o
    # PyInstaller não as tenha coletado. Copia apenas as que ainda faltam.
    log "Injetando libs xcb (cursor/video/xkb) na raiz _internal/ (falta apenas)..."
    for lib in \
        libxcb-cursor.so.0 \
        libxcb.so.1 \
        libxcb-glx.so.0 libxcb-icccm.so.4 libxcb-image.so.0 \
        libxcb-keysyms.so.1 libxcb-randr.so.0 libxcb-render.so.0 \
        libxcb-render-util.so.0 libxcb-shape.so.0 libxcb-shm.so.0 \
        libxcb-sync.so.1 libxcb-util.so.1 libxcb-xfixes.so.0 \
        libxcb-xkb.so.1; do
        if [ -e "$root_internal/$lib" ] || [ -L "$root_internal/$lib" ]; then
            continue
        fi
        # Procura a .so em diretórios comuns (lib64 + lib e subpastas)
        src="$(find /usr/lib /lib /usr/local/lib -name "$lib" 2>/dev/null | head -n1 || true)"
        if [ -n "$src" ]; then
            cp -L "$src" "$root_internal/$lib"
            log "  + $lib"
        else
            log "  (ausente no SO, pulando $lib)"
        fi
    done
fi

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
StartupWMClass=VoiceNeves
EOF

log "Gerando VoiceNeves-x86_64.AppImage..."
# Instâncias rodando seguram o arquivo ("Text file busy"); encerra antes.
pkill -9 -f 'VoiceNeves' 2>/dev/null || true
sleep 1
rm -f VoiceNeves-x86_64.AppImage
./"$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" VoiceNeves-x86_64.AppImage \
    > /dev/null 2>&1 || err "falha ao gerar o AppImage"

log "Pronto: VoiceNeves-x86_64.AppImage ($(du -h VoiceNeves-x86_64.AppImage | cut -f1))"
