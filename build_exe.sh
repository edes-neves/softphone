#!/usr/bin/env bash
# build_exe.sh — Gera o executável VoiceNeves com PyInstaller (+ AppImage).
# Uso: ./build_exe.sh [--no-sip]
#   --no-sip  empacota SOMENTE a UI (sem pjsua2) — útil para testar o pacote
#             antes de rodar ./build_pjsip.sh. Chamadas SIP ficam desativadas.
set -Eeuo pipefail

log()  { printf '\n\033[1;34m[build_exe]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[AVISO]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[ERRO]\033[0m %s\n' "$*" >&2; exit 1; }

cd "$(dirname "$0")"
PY=".venv/bin/python"

REQUIRE_SIP=1
for arg in "$@"; do
    case "$arg" in
        --no-sip) REQUIRE_SIP=0 ;;
        -h|--help)
            sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) err "opção desconhecida: $arg (use --help)" ;;
    esac
done

[ -x "$PY" ] || err "venv não encontrado em .venv/
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"

# ---- 1. Pré-requisitos ------------------------------------------------------
"$PY" -c "import PySide6, keyring, pynput" 2>/dev/null || {
    log "Instalando dependências do venv (requirements.txt)..."
    "$PY" -m pip install -r requirements.txt
}
command -v patchelf >/dev/null 2>&1 || {
    log "Instalando patchelf (precisa de sudo)..."
    sudo apt install -y patchelf
}
"$PY" -m PyInstaller --version >/dev/null 2>&1 || {
    log "Instalando pyinstaller no venv..."
    "$PY" -m pip install pyinstaller
}

# ---- 2. Bundle do pjsua2: binding + libs juntos, rpath portátil -------------
# Onde o build_pjsip.sh deixa o binding (qualquer um dos dois serve):
#   - site-packages do venv  (cópia instalada pelo build_pjsip.sh)
#   - third_party/pjsip-dist (o sip_backend.py já adiciona no sys.path)
BUNDLE="build/pjsua2_bundle"
PJSIP_DIST="third_party/pjsip-dist"
SITE_DIR="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
# Sufixo ABI do Python do venv (ex.: .cpython-312-x86_64-linux-gnu.so)
EXT="$("$PY" -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"
BINDING_NAME="_pjsua2${EXT}"

PJSUA2_PY=""
PJSUA2_SO=""
for d in "$SITE_DIR" "$PJSIP_DIST"; do
    if [ -z "$PJSUA2_PY" ] && [ -f "$d/pjsua2.py" ]; then
        PJSUA2_PY="$d/pjsua2.py"
    fi
    if [ -z "$PJSUA2_SO" ] && [ -f "$d/$BINDING_NAME" ]; then
        PJSUA2_SO="$d/$BINDING_NAME"
    fi
done

HAVE_SIP=0
if [ -n "$PJSUA2_PY" ] && [ -n "$PJSUA2_SO" ] && compgen -G "$PJSIP_DIST/lib/lib*.so*" >/dev/null; then
    HAVE_SIP=1
elif [ "$REQUIRE_SIP" -eq 1 ]; then
    err "pjsua2 indisponível. Faltando:
  binding: ${SITE_DIR}/${BINDING_NAME}  ou  ${PJSIP_DIST}/${BINDING_NAME}
  pjsua2.py e libs: ${PJSIP_DIST}/lib/lib*.so*
Compile antes com:  ./build_pjsip.sh
Ou empacote só a UI com:  ./build_exe.sh --no-sip"
else
    warn "pjsua2 não encontrado — gerando executável SOMENTE com a UI"
    warn "(chamadas SIP desativadas). Para SIP completo: ./build_pjsip.sh"
fi

SIP_ARGS=()
if [ "$HAVE_SIP" -eq 1 ]; then
    log "Preparando $BUNDLE..."
    # Limpa restos de builds antigos (evita misturar libs incompatíveis)
    rm -rf "$BUNDLE"
    mkdir -p "$BUNDLE"
    cp "$PJSUA2_PY" "$BUNDLE/"
    cp "$PJSUA2_SO" "$BUNDLE/"
    cp "$PJSIP_DIST"/lib/lib*.so* "$BUNDLE/"
    patchelf --set-rpath '$ORIGIN' "$BUNDLE/$BINDING_NAME"

    SIP_ARGS=(
        --paths "$BUNDLE"
        --add-binary "$BUNDLE/$BINDING_NAME:."
        --add-binary "$BUNDLE/lib*.so*:."
        --hidden-import pjsua2
    )
fi

# ---- 3. PyInstaller ---------------------------------------------------------
log "Gerando executável..."
"$PY" -m PyInstaller --clean --noconfirm \
    --name VoiceNeves \
    softphone.py \
    "${SIP_ARGS[@]}" \
    --add-data "ringtone.wav:." \
    --add-data "Icone.png:." \
    --add-data "voiceneves.png:." \
    --collect-submodules voice_neves \
    --collect-submodules keyring \
    --collect-data keyring \
    --hidden-import pynput

log "Pronto: dist/VoiceNeves/VoiceNeves"
log "Teste: cd dist/VoiceNeves && ./VoiceNeves"

# ---- 3b. Libs de áudio do SISTEMA não vão no pacote -------------------------
# A libasound/libpulse embutidas (do SO onde compilou) conflitam com os
# plugins de áudio do SO de destino (ex.: PipeWire no Ubuntu 24+), deixando
# o app mudo. Cada máquina deve usar a própria pilha de som.
log "Removendo libasound/libpulse do bundle (usam-se as do SO)..."
rm -f dist/VoiceNeves/_internal/libasound* \
      dist/VoiceNeves/_internal/libpulse*

# ---- 3c. libxkbcommon do SISTEMA (evita segfault em hosts novos) -----------
# A libxkbcommon empacotada (build Ubuntu 22.04/veículo old Qt) crasha ao
# processar eventos de teclado em distribuições com GLib/Xwayland/xkb novos
# (ex.: Ubuntu 26.04) — segfault em xkb_state_key_get_layout. Como o soname
# .so.0 é ABI estável e todo desktop tem a biblioteca do sistema, removemos a
# embutida para o runtime usar a do SO de destino.
log "Removendo libxkbcommon do bundle (usam-se as do SO)..."
find dist/VoiceNeves -name 'libxkbcommon*.so*' -delete

# ---- 3e. Autossuficiência do Qt Xcb (impede erro libxcb-cursor no destino) ---
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
