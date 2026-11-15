#!/usr/bin/env bash
# build_deb.sh — Empacota o binário do PyInstaller (dist/VoiceNeves) em um .deb.
#
# Requer que ./build_exe.sh já tenha sido executado (gera dist/VoiceNeves/, que
# já traz o Python embutido, o binding pjsua2 e as libs do PJSIP/codecs). Assim
# o pacote NÃO depende do Python nem das libs de codec da máquina de destino —
# apenas das bibliotecas de sistema que o build_exe.sh deliberadamente deixa
# para o SO (áudio/pulse/xkb/GL), garantindo instalação nas principais distros.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# A versão vem de voice_neves/__init__.py (fonte da verdade, bumpada pelo
# bump.sh). O version.json só é regenerado no fim do release.yml, então lê-lo
# aqui daria a versão ANTERIOR. Fallback para version.json se necessário.
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' voice_neves/__init__.py | tr -d '[:space:]')"
if [ -z "$VERSION" ]; then
  VERSION="$(python3 -c "import json; print(json.load(open('version.json'))['version'].strip())")"
fi
ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m | sed 's/x86_64/amd64/')"
PKG="VoiceNeves-${VERSION}-${ARCH}.deb"

APP_SRC="dist/VoiceNeves"
if [ ! -x "$APP_SRC/VoiceNeves" ]; then
  echo "ERRO: '$APP_SRC/VoiceNeves' não encontrado." >&2
  echo "Gere o binário antes: ./build_exe.sh" >&2
  exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# ---- Aplicativo (bundle autossuficiente) ------------------------------------
mkdir -p "$STAGE/opt/voiceneves"
cp -a "$APP_SRC/." "$STAGE/opt/voiceneves/"

# ---- Launcher ---------------------------------------------------------------
mkdir -p "$STAGE/usr/bin"
cat > "$STAGE/usr/bin/voiceneves" << 'LAUNCH'
#!/usr/bin/env bash
exec /opt/voiceneves/VoiceNeves "$@"
LAUNCH
chmod 755 "$STAGE/usr/bin/voiceneves"

# ---- Atalho (.desktop) e ícones --------------------------------------------
# O Exec precisa ser "voiceneves" (nome do launcher instalado em /usr/bin) e o
# Icon precisa bater com os PNGs instalados em hicolor — era isso que impedia o
# atalho de aparecer no menu de aplicativos.
mkdir -p "$STAGE/usr/share/applications"
cp VoiceNeves.desktop "$STAGE/usr/share/applications/com.edesneves.voiceneves.desktop"
cp VoiceNeves.desktop "$STAGE/usr/share/applications/voiceneves.desktop"

mkdir -p "$STAGE/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$STAGE/usr/share/icons/hicolor/512x512/apps"
cp voiceneves.png "$STAGE/usr/share/icons/hicolor/256x256/apps/voiceneves.png"
cp voiceneves.png "$STAGE/usr/share/icons/hicolor/512x512/apps/voiceneves.png"

# ---- pós-instalação: atualiza caches de menu/ícone (best-effort) ------------
cat > "$STAGE/after-install.sh" << 'AFTER'
#!/bin/sh
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
AFTER
chmod 755 "$STAGE/after-install.sh"

# ---- Build do .deb ----------------------------------------------------------
# Dependências: só as libs de sistema que o bundle deixa de fora (ver
# build_exe.sh). Alternativas cobrem os renomeados recentes (t64 no Ubuntu 24+).
fpm -s dir -t deb -n voiceneves -v "$VERSION" --architecture "$ARCH" \
  --iteration 1 \
  --license "MIT" \
  --description "VoiceNeves SIP Softphone" \
  --maintainer "José Edes Neves <edes-neves@users.noreply.github.com>" \
  --url "https://github.com/edes-neves/softphone" \
  --depends "libasound2 | libasound2t64" \
  --depends "libpulse0" \
  --depends "libxkbcommon0" \
  --depends "libxcb-cursor0" \
  --depends "libgl1" \
  --after-install "$STAGE/after-install.sh" \
  -C "$STAGE" \
  opt usr

mv voiceneves_*.deb "$PKG" 2>/dev/null || true

echo "Gerado: $PKG"
ls -lh "$PKG" 2>/dev/null || ls -lh voiceneves* 2>/dev/null
