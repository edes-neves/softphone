#!/usr/bin/env bash
#
# build_pjsip.sh
# ----------------------------------------------------------------------------
# Recompilação do zero do PJSIP + binding pjsua2 para Python 3.14.4 no
# Ubuntu 26.04, com codecs de áudio (Opus) e vídeo (H.264/VP8) habilitados.
#
# Uso:
#   chmod +x build_pjsip.sh
#   ./build_pjsip.sh
#
# O script é linear e interrompe no primeiro erro (set -e).
# ----------------------------------------------------------------------------

set -Eeuo pipefail

# ---------- Variáveis ajustáveis --------------------------------------------
PJSIP_DIR="${PJSIP_DIR:-$HOME/Público/softphone/third_party/pjsip-opus-g729}"
PYBIN="${PYBIN:-/usr/bin/python3.14}"
VENV_DIR="${VENV_DIR:-$HOME/Público/softphone/venv}"
INSTALL_PREFIX="${INSTALL_PREFIX:-/usr/local}"
JOBS="$(nproc)"

export CFLAGS="-O2 -fPIC -Wno-error"
export CXXFLAGS="-O2 -fPIC -Wno-error"
export LDFLAGS="-Wl,-rpath,${INSTALL_PREFIX}/lib"
export PYTHON="${PYBIN}"

# Torna o venv reutilizável nas chamadas internas
export VENV_PY="${VENV_DIR}/bin/python"
export VENV_PIP="${VENV_DIR}/bin/pip"

# ---------- Helpers ---------------------------------------------------------
log()  { printf '\n\033[1;34m[build_pjsip]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[AVISO]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[ERRO]\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

step() { log "==== $* ===="; }

trap 'err "Falha na linha $LINENO do comando: $BASH_COMMAND"' ERR

# Verifica presença de comandos obrigatórios antes de prosseguir
require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "Comando não encontrado: $1"
}

# ----------------------------------------------------------------------------
step "1. Pré-verificação do ambiente"
require_cmd sudo
require_cmd make
require_cmd pkg-config
require_cmd swig
[ -x "${PYBIN}" ]  || die "Python 3.14 não encontrado em ${PYBIN}. Instale python3.14 / python3.14-dev."
"${PYBIN}" --version | grep -q 'Python 3.14' || die "Esperado Python 3.14.x, encontrei: $(${PYBIN} --version)"
[ -d "${PJSIP_DIR}" ] || die "Diretório do PJSIP não encontrado: ${PJSIP_DIR}"

# ----------------------------------------------------------------------------
step "2. Instalação das dependências do sistema (APT)"
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    pkg-config \
    uuid-dev \
    swig \
    python3.14-dev \
    python3.14-venv \
    libssl-dev \
    libopus-dev \
    libopenh264-dev \
    libvpx-dev \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libutil-dev \
    libasound2-dev \
    libpulse-dev \
    patchelf

# ----------------------------------------------------------------------------
step "3. Criação/ativação do virtualenv Python 3.14 (PEP 668 isolada)"
if [ ! -d "${VENV_DIR}" ]; then
    "${PYBIN}" -m venv "${VENV_DIR}"
fi
# Sem --system-site-packages: protege contra a PEP 668 do Python do sistema.
"${VENV_PIP}" install --upgrade pip setuptools wheel

# Confirma que o venv aponta para o Python esperado
"${VENV_PY}" --version
"${VENV_PY}" -c "import sys; assert sys.prefix=='${VENV_DIR}', 'venv fora do escopo'"

# ----------------------------------------------------------------------------
step "4. Customização mandatória do pjlib/include/pj/config_site.h"
CONFIG_SITE="${PJSIP_DIR}/pjlib/include/pj/config_site.h"
cat > "${CONFIG_SITE}" <<'EOF'
/* config_site.h — gerado por build_pjsip.sh
 * Macros de nível comercial: SSL/TLS, SRTP, Opus, vídeo (H.264/VP8),
 * WebRTC AEC, IPv6 e limites aumentados.
 */
#define PJ_HAS_SSL_SOCK 1
#define PJMEDIA_HAS_SRTP 1
#define PJMEDIA_HAS_OPUS_CODEC 1
#define PJMEDIA_HAS_VIDEO 1
#define PJMEDIA_HAS_FFMPEG 1
#define PJMEDIA_HAS_OPENH264_CODEC 1
#define PJMEDIA_HAS_VPX_CODEC 1
#define PJMEDIA_HAS_WEBRTC_AEC 1
#define PJ_HAS_IPV6 1
#define PJ_IOQUEUE_MAX_HANDLES 1024
#define PJ_CONFIG_MAX_CALLS 32
EOF
log "config_site.h gravado: ${CONFIG_SITE}"

# ----------------------------------------------------------------------------
step "5. Limpeza da compilação anterior (make distclean)"
cd "${PJSIP_DIR}"
if [ -f Makefile ]; then
    make distclean || warn "make distclean falhou (pode ser primeira compilação) — prosseguindo"
fi

# ----------------------------------------------------------------------------
step "6. ./configure para Python 3.14 (com Opus, SSL, OpenH264, FFmpeg, SWIG)"

./configure \
    --prefix="${INSTALL_PREFIX}" \
    --enable-shared \
    --enable-video \
    --enable-ext-sound \
    --enable-libwebrtc \
    --with-opus \
    --with-ssl \
    --with-openh264 \
    --with-ffmpeg \
    --with-swig

# ----------------------------------------------------------------------------
step "7. Auditoria do relatório do configure"
log "Trecho relevante do config.log / saída do configure:"
# Re-exibe as linhas-chave que o configure imprime ao final
grep -Ei 'Opus|OpenH264|FFmpeg|SSL|TLS|VPX|Video|libwebrtc|SRTP' config.log 2>/dev/null \
    | sort -u | tee configure-summary.txt || warn "Não foi possível extrair summary do config.log"

# Verificações explícitas: falha se algum recurso crítico não ficou ativo
check_yes() {
    local key="$1"
    if ! grep -Ei "(${key}[[:space:]]*[:=][[:space:]]*yes|${key}.+enabled)" config.log >/dev/null 2>&1; then
        warn "${key} não apareceu como 'yes' — revise configure-summary.txt antes de prosseguir."
    fi
}
for k in OPUS OPENH264 FFMPEG SSL TLS VPX VIDEO SRTP WEBRTC; do
    check_yes "$k"
done

# ----------------------------------------------------------------------------
step "8. Compilação e instalação da base do PJSIP"
make dep
make -j"${JOBS}"
sudo make install
sudo ldconfig

# ----------------------------------------------------------------------------
step "9. Geração do binding pjsua2 Python 3.14 (direto no venv)"
PYBIND="${PJSIP_DIR}/pjsip-apps/src/swig/python"
cd "${PYBIND}"

# Garante que o swig use o Python 3.14 do venv ativo
export PYTHONPATH=""  # evita contaminação
"${VENV_PIP}" install -U setuptools  # obrigatório p/ Python 3.14

# O Make do swig usa PYTHON=/usr/bin/python3 por padrão; sobrescrevemos.
make PYTHON="${VENV_PY}"

# Instala o módulo pjsua2 dentro do venv (não toca no site-packages do sistema)
"${VENV_PY}" setup.py install

# ----------------------------------------------------------------------------
step "10. Prova-final: import + version do módulo instalado no venv"
"${VENV_PY}" - <<'PY'
import sys, site
print("python :", sys.executable)
print("prefix :", sys.prefix)
try:
    import pjsua2 as pj
    print("pjsua2 OK, arquivo:", pj.__file__)
except Exception as e:
    print("FALHA ao importar pjsua2:", e)
    raise
PY

log "Concluído. Ative o venv com:  source ${VENV_DIR}/bin/activate"
log "Rode o teste de codecs:        ${VENV_PY} test_pjsua2_codecs.py"