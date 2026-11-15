#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="$(python3 -c "import json; print(json.load(open('version.json'))['version'])")"
ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m | sed 's/x86_64/amd64/')"
PKG="voiceneves_${VERSION}_${ARCH}.deb"

rm -rf /tmp/voiceneves-deb
mkdir -p /tmp/voiceneves-deb/opt/voiceneves
mkdir -p /tmp/voiceneves-deb/usr/bin
mkdir -p /tmp/voiceneves-deb/usr/share/applications
mkdir -p /tmp/voiceneves-deb/usr/share/icons/hicolor/256x256/apps
mkdir -p /tmp/voiceneves-deb/usr/share/icons/hicolor/512x512/apps

# Copia app
rsync -a --exclude='.git' --exclude='.github' --exclude='.venv' --exclude='third_party' --exclude='*.AppImage' --exclude='dist' --exclude='build' --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' --exclude='.ruff_cache' --exclude='packaging' --exclude='softphone-master.zip' ./ /tmp/voiceneves-deb/opt/voiceneves/

# Launcher
cat > /tmp/voiceneves-deb/usr/bin/voiceneves << 'LAUNCH'
#!/usr/bin/env bash
cd /opt/voiceneves
exec .venv/bin/python softphone.py "$@"
LAUNCH
chmod 755 /tmp/voiceneves-deb/usr/bin/voiceneves

# .desktop
cp VoiceNeves.desktop /tmp/voiceneves-deb/usr/share/applications/com.edesneves.voiceneves.desktop || cp VoiceNeves.desktop /tmp/voiceneves-deb/usr/share/applications/voiceneves.desktop

# Icons
cp voiceneves.png /tmp/voiceneves-deb/usr/share/icons/hicolor/256x256/apps/voiceneves.png 2>/dev/null || true
cp voiceneves.png /tmp/voiceneves-deb/usr/share/icons/hicolor/512x512/apps/voiceneves.png 2>/dev/null || true

# Build deb
fpm -s dir -t deb -n voiceneves -v "$VERSION" --architecture "$ARCH" \
  --description "VoiceNeves SIP Softphone" \
  --maintainer "José Edes Neves <edes-neves@users.noreply.github.com>" \
  --url "https://github.com/edes-neves/softphone" \
  --depends python3 \
  --depends python3-pyside6.qtcore --depends python3-pyside6.qtgui --depends python3-pyside6.qtwidgets \
  --depends python3-pyside6.qtnetwork --depends python3-pyside6.qtmultimedia --depends python3-pyside6.qtsvg \
  --depends libasound2 --depends libxcb-cursor0 --depends libssl3 --depends libopus0 --depends libvpx7 \
  -C /tmp/voiceneves-deb \
  opt usr

mv voiceneves_${VERSION}_${ARCH}.deb "$PKG"
echo "Gerado: $PKG"
