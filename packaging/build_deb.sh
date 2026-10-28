#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="$(python3 -c "import json; print(json.load(open('version.json'))['version'])")"
ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m | sed 's/x86_64/amd64/')"
PKG="VoiceNeves-${VERSION}-${ARCH}.deb"

rm -rf /tmp/voiceneves-deb
mkdir -p /tmp/voiceneves-deb/opt/voiceneves
mkdir -p /tmp/voiceneves-deb/usr/bin
mkdir -p /tmp/voiceneves-deb/usr/share/applications
mkdir -p /tmp/voiceneves-deb/usr/share/icons/hicolor/256x256/apps
mkdir -p /tmp/voiceneves-deb/usr/share/icons/hicolor/512x512/apps

# Copia app (inclui .venv com todas as dependências)
rsync -a \
  --exclude='.git' \
  --exclude='.github' \
  --exclude='*.AppImage' \
  --exclude='dist' \
  --exclude='build' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache' \
  --exclude='.ruff_cache' \
  --exclude='packaging' \
  --exclude='softphone-master.zip' \
  ./ /tmp/voiceneves-deb/opt/voiceneves/

# Garante pjsua2 e libs no pacote
mkdir -p /tmp/voiceneves-deb/opt/voiceneves/third_party/pjsip-dist/lib

# Copia libs pjsip dist se existirem
if [ -d "third_party/pjsip-dist/lib" ]; then
  cp -f third_party/pjsip-dist/lib/*.so* /tmp/voiceneves-deb/opt/voiceneves/third_party/pjsip-dist/lib/ 2>/dev/null || true
fi

# Copia para lib/ também para facilitar
mkdir -p /tmp/voiceneves-deb/opt/voiceneves/lib
cp -f /tmp/voiceneves-deb/opt/voiceneves/third_party/pjsip-dist/lib/*.so* /tmp/voiceneves-deb/opt/voiceneves/lib/ 2>/dev/null || true

# Garante que pjsua2 fique acessível (pode já estar em .venv/site-packages)
PYVER="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
if [ -d "/tmp/voiceneves-deb/opt/voiceneves/.venv/lib/python${PYVER}/site-packages" ]; then
  for f in pjsua2.py _pjsua2*.so libpjsua2*.so* libpjsua*.so* libpjsip*.so* libpj*.so* libpjmedia*.so* libpjnath*.so*; do
    cp -f "/tmp/voiceneves-deb/opt/voiceneves/.venv/lib/python${PYVER}/site-packages/$f" /tmp/voiceneves-deb/opt/voiceneves/ 2>/dev/null || true
    cp -f "/tmp/voiceneves-deb/opt/voiceneves/.venv/lib/python${PYVER}/site-packages/$f" /tmp/voiceneves-deb/opt/voiceneves/lib/ 2>/dev/null || true
  done
fi

# Launcher com venv bundled
cat > /tmp/voiceneves-deb/usr/bin/voiceneves << 'LAUNCH'
#!/usr/bin/env bash
APP_DIR=/opt/voiceneves
export LD_LIBRARY_PATH="$APP_DIR/lib:$APP_DIR/third_party/pjsip-dist/lib:${LD_LIBRARY_PATH:-}"
cd "$APP_DIR"
exec "$APP_DIR/.venv/bin/python" softphone.py "$@"
LAUNCH
chmod 755 /tmp/voiceneves-deb/usr/bin/voiceneves

# .desktop
if [ -f VoiceNeves.desktop ]; then
  cp VoiceNeves.desktop /tmp/voiceneves-deb/usr/share/applications/com.edesneves.voiceneves.desktop
  cp VoiceNeves.desktop /tmp/voiceneves-deb/usr/share/applications/voiceneves.desktop 2>/dev/null || true
fi

# Icons
if [ -f voiceneves.png ]; then
  cp voiceneves.png /tmp/voiceneves-deb/usr/share/icons/hicolor/256x256/apps/voiceneves.png 2>/dev/null || true
  cp voiceneves.png /tmp/voiceneves-deb/usr/share/icons/hicolor/512x512/apps/voiceneves.png 2>/dev/null || true
fi

# Build deb com fpm (sem dependências do PySide6 do sistema)
fpm -s dir -t deb -n voiceneves -v "$VERSION" --architecture "$ARCH" \
  --iteration 1 \
  --license "MIT" \
  --description "VoiceNeves SIP Softphone" \
  --maintainer "José Edes Neves <edes-neves@users.noreply.github.com>" \
  --url "https://github.com/edes-neves/softphone" \
  --depends python3 \
  --depends libasound2 \
  --depends libssl3 \
  --depends libopus0 \
  --depends libvpx7 \
  --depends libgsm1 \
  --depends libspeexdsp1 \
  --depends libxcb-cursor0 \
  --depends libxkbcommon0 \
  -C /tmp/voiceneves-deb \
  opt usr

mv "voiceneves_${VERSION}_${ARCH}.deb" "$PKG" 2>/dev/null || mv "voiceneves_${VERSION}-${ARCH}.deb" "$PKG" 2>/dev/null || mv voiceneves*.deb "$PKG" 2>/dev/null || true

echo "Gerado: $PKG"
ls -lh "$PKG" 2>/dev/null || ls -lh voiceneves* 2>/dev/null
