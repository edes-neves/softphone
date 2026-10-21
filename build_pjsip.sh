#!/usr/bin/env bash
#
# build_pjsip.sh
# ----------------------------------------------------------------------------
# Compila o PJSIP (pjproject) + binding Python `pjsua2` para o .venv DO
# PROJETO (Python do .venv, hoje 3.12.x), com codecs de áudio (Opus, G.729)
# e vídeo (H.264/VP8) habilitados.
#
# Layout gerado — é exatamente o que voice_neves/sip_backend.py e
# build_exe.sh esperam:
#
#   third_party/pjsip-opus-g729/     fonte do pjproject      (PJSIP_DIR)
#   third_party/pjsip-dist/          prefixo de instalação   (INSTALL_PREFIX)
#       ├── pjsua2.py                binding (sip_backend adiciona no sys.path)
#       ├── _pjsua2.cpython-*.so
#       └── lib/libpj*.so*           libs (empacotadas pelo build_exe.sh)
#   .venv/lib/python3.x/site-packages/   cópia do binding p/ `import pjsua2`
#
# Uso:
#   chmod +x build_pjsip.sh
#   ./build_pjsip.sh
#
# Variáveis opcionais (sobrescrevem os padrões acima):
#   PJSIP_DIR, VENV_DIR, INSTALL_PREFIX, PYBIN, JOBS
# ----------------------------------------------------------------------------

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# ---------- Variáveis (padrão = layout do projeto) ---------------------------
PJSIP_DIR="${PJSIP_DIR:-${SCRIPT_DIR}/third_party/pjsip-opus-g729}"
VENV_DIR="${VENV_DIR:-${SCRIPT_DIR}/.venv}"
INSTALL_PREFIX="${INSTALL_PREFIX:-${SCRIPT_DIR}/third_party/pjsip-dist}"
PYBIN="${PYBIN:-${VENV_DIR}/bin/python}"
JOBS="${JOBS:-$(nproc)}"

VENV_PY="${VENV_DIR}/bin/python"
VENV_PIP="${VENV_DIR}/bin/pip"

export CFLAGS="-O2 -fPIC -Wno-error"
export CXXFLAGS="-O2 -fPIC -Wno-error"
# rpath absoluto: o binding e as libs acham libpj* rodando direto da fonte.
export LDFLAGS="-Wl,-rpath,${INSTALL_PREFIX}/lib"
export PYTHON="${PYBIN}"
# setup.py do binding lê version.mak via PJDIR (necessário no build do wheel)
export PJDIR="${PJSIP_DIR}"

# ---------- Helpers ---------------------------------------------------------
log()  { printf '\n\033[1;34m[build_pjsip]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[AVISO]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[ERRO]\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

step() { log "==== $* ===="; }

trap 'err "Falha na linha $LINENO do comando: $BASH_COMMAND"' ERR

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "Comando não encontrado: $1"
}

# ----------------------------------------------------------------------------
step "1. Pré-verificação do ambiente"
require_cmd sudo
require_cmd make
require_cmd gcc
require_cmd g++
require_cmd pkg-config

if [ ! -x "${VENV_PY}" ]; then
    die "venv não encontrado: ${VENV_DIR}
  Crie-o antes:  python3 -m venv ${VENV_DIR}
                 ${VENV_PIP} install -r ${SCRIPT_DIR}/requirements.txt"
fi

if [ ! -x "${PYBIN}" ]; then
    die "Python não encontrado: ${PYBIN}
  O PYBIN padrão é o Python do venv (${VENV_PY}). Instale o venv ou
  exporte PYBIN=<outro python3> com a MESMA versão (major.minor) do venv."
fi

PYBIN_V="$("${PYBIN}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
VENV_V="$("${VENV_PY}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ "${PYBIN_V}" != "${VENV_V}" ]; then
    die "Incompatibilidade de versão: PYBIN=${PYBIN} é Python ${PYBIN_V}, mas o venv é ${VENV_V}.
  O binding precisa ser gerado com o Python ${VENV_V} do venv.
  Use PYBIN=${VENV_PY} (padrão) ou recrie o venv."
fi

if ! "${VENV_PY}" -c 'import os, sys, sysconfig; \
p = os.path.join(sysconfig.get_paths()["include"], "Python.h"); \
raise SystemExit(0 if os.path.exists(p) else 1)'; then
    die "Python.h não encontrado para o venv (${VENV_V}).
  Instale os headers desse interpretador (ex.: python${VENV_V}-dev, ou
  recompile via pyenv com os headers incluídos)."
fi

[ -d "${PJSIP_DIR}" ] || die "Fonte do PJSIP não encontrada: ${PJSIP_DIR}
  Baixe o pjproject 2.14 e extraia/clones nesse diretório (PJSIP_DIR=... para outro caminho)."

# ----------------------------------------------------------------------------
step "2. Instalação das dependências do sistema (APT)"
# Obs.: sem python3.x-dev/venv: o venv usa o próprio Python (pyenv/sistema)
# já com headers (checado no passo 1). `libutil-dev` não existe mais e quebrava
# o apt; `--enable-ext-sound` foi removido do configure (desativava o backend
# ALSA e deixava as chamadas mudas).
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    pkg-config \
    uuid-dev \
    swig \
    autoconf \
    libtool \
    patchelf \
    libssl-dev \
    libopus-dev \
    libbcg729-dev \
    libopenh264-dev \
    libvpx-dev \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    libavdevice-dev \
    libasound2-dev \
    libpulse-dev \
    libsdl2-dev \
    libv4l-dev \
    libsamplerate0-dev \
    libspeexdsp-dev \
    libupnp-dev \
    doxygen

require_cmd swig
require_cmd patchelf

# ----------------------------------------------------------------------------
step "3. venv do projeto: upgrade de ferramentas de build"
"${VENV_PIP}" install --upgrade pip setuptools wheel
"${VENV_PY}" --version
"${VENV_PY}" -c "import sys; assert sys.prefix=='${VENV_DIR}', 'venv fora do escopo: '+sys.prefix"

# ----------------------------------------------------------------------------
step "4. Customização mandatória do pjlib/include/pj/config_site.h"
CONFIG_SITE="${PJSIP_DIR}/pjlib/include/pj/config_site.h"
mkdir -p "$(dirname "${CONFIG_SITE}")"
cat > "${CONFIG_SITE}" <<'EOF'
/* config_site.h — gerado por build_pjsip.sh
 *
 * SOMENTE macros que o ./configure não define sozinho.
 * Codecs (Opus, G.729/BCG729), H.264, VP8, FFmpeg e SSL/TLS são detectados
 * pelo próprio configure a partir das libs do sistema e gravados em
 * pjlib/include/pj/compat/os_auto.h (+ CFLAGS em build.mak) — não force aqui,
 * senão o build quebra quando a lib correspondente não estiver instalada.
 */
#define PJMEDIA_HAS_VIDEO         1  /* habilita a pilha de vídeo */
#define PJMEDIA_HAS_VPX_CODEC_VP9 1  /* habilita VP9 (default: 0) */
#define PJMEDIA_HAS_WEBRTC_AEC    1  /* AEC WebRTC (webrtc em third_party) */
#define PJMEDIA_HAS_SRTP          1  /* SRTP (libsrtp em third_party) */
#define PJ_HAS_IPV6               1
#define PJ_IOQUEUE_MAX_HANDLES    1024
#define PJSUA_MAX_CALLS           32 /* chamadas simultâneas (default: 4) */
EOF
log "config_site.h gravado: ${CONFIG_SITE}"

# ----------------------------------------------------------------------------
step "5. Limpeza da compilação anterior e geração do ./configure"
cd "${PJSIP_DIR}"
if [ -f build.mak ] || [ -f Makefile ]; then
    make distclean || warn "make distclean falhou (pode ser primeira compilação) — prosseguindo"
fi

# Fonte vinda de git não traz o ./configure gerado (só a release/tarball traz).
if [ ! -x ./configure ] && [ -f aconfigure.ac ]; then
    log "configure ausente — gerando a partir de aconfigure.ac"
    require_cmd autoconf
    autoconf -o configure aconfigure.ac || die "autoconf falhou ao gerar o configure"
    chmod +x configure
fi
[ -x ./configure ] || die "configure não encontrado em ${PJSIP_DIR}
  Use a release/tarball do pjproject 2.14 ou tenha autoconf + aconfigure.ac."

# ----------------------------------------------------------------------------
step "6. ./configure (prefixo do projeto, Opus, G.729, SSL, vídeo)"
# Flags removidas em relação à versão antiga:
#   --enable-ext-sound  → DESATIVAVA o backend de som (chamadas mudas);
#                         o app usa ALSA (bridge p/ PipeWire/PulseAudio).
#   --with-swig         → não existe no configure do pjproject (o binding
#                         SWIG é construído à parte, passo 9).
#   --enable-libwebrtc  → ARMADILHA do aconfigure 2.17: passar ESSA flag
#                         (mesmo com valor "yes") faz `test ${enable_libwebrtc+y}`
#                         ser verdadeiro e pula o bloco `else` que detecta
#                         `ac_webrtc_instset` (sse2/neon/...). Resultado: o
#                         instset fica VAZIO, `os-auto.mak` cai no ramo genérico
#                         e `complex_fft.o` é linkado em dobro
#                         ("múltiplas definições de WebRtcSpl_ComplexFFT").
#                         O WebRTC já vem LIGADO por padrão — não passar a flag.
#
# Cobertura de recursos exigida pelo projeto:
#   Áudio : Opus, G.729/BCG729, iLBC, GSM, G.711 (PCMU/PCMA), G.722,
#           Speex, L16 + resample por libsamplerate e AEC (Speex/WebRTC).
#   Vídeo : VP8, VP9, H.263, H.264 (OpenH264 + FFmpeg), V4L2, SDL.
#   Seg.  : SSL/TLS (OpenSSL) + SRTP (libsrtp em third_party).
#   Áudio : ALSA (PipeWire/PulseAudio via bridge) + SDL.
# DSP   : resample, filtros pequeno/grande, AEC (--enable-speex-aec e
#           WebRTC AEC — este já ativo por padrão; ver nota acima).
#   NAT   : PJNATH + UPnP (libupnp) para travessia de NAT/firewall.
./configure \
    --prefix="${INSTALL_PREFIX}" \
    --enable-shared \
    --enable-video \
    --enable-speex-aec \
    --enable-libsamplerate \
    --with-opus \
    --with-bcg729 \
    --with-ssl \
    --with-openh264 \
    --with-vpx \
    --with-ffmpeg \
    --with-upnp

# ----------------------------------------------------------------------------
step "7. Auditoria do relatório do configure"
log "Trecho relevante do config.log / saída do configure:"
grep -Ei 'Opus|bcg729|OpenH264|FFmpeg|SSL|TLS|VPX|VP8|VP9|Video|libwebrtc|SRTP|ALSA|SDL|libsamplerate|Speex|UPnP' config.log 2>/dev/null \
    | sort -u | tee configure-summary.txt || warn "Não foi possível extrair summary do config.log"

# Guarda de sanidade do WebRTC (pjproject 2.17): se `ac_webrtc_instset` vier
# VAZIO, o `os-auto.mak` fica com condições `findstring sse2,` sempre falsas,
# cai no ramo genérico e linka `complex_fft.o` em dobro (a lista base
# WEBRTC_OBJS já o contém) → "múltiplas definições de WebRtcSpl_ComplexFFT".
# O flag `--enable-libwebrtc` é a causa (ver nota do passo 6); esta guarda é
# um cinto-e-suspensório que fixa o instset correto pela arquitetura do host.
WEBRTC_OS_MAK="${PJSIP_DIR}/third_party/build/os-auto.mak"
if grep -q "findstring sse2,)" "${WEBRTC_OS_MAK}" 2>/dev/null; then
    case "$(uname -m)" in
        x86_64|amd64|i?86) WEBRTC_INSTSET="sse2" ;;
        aarch64|arm64)     WEBRTC_INSTSET="neon" ;;
        *)                 WEBRTC_INSTSET="generic" ;;
    esac
    sed -i "s/findstring sse2,)/findstring sse2,${WEBRTC_INSTSET})/g" "${WEBRTC_OS_MAK}"
    log "os-auto.mak: WebRTC instset vazio → fixado em '${WEBRTC_INSTSET}' (host $(uname -m))"
fi

# Onde o configure gravou os AC_DEFINEs
OS_AUTO="${PJSIP_DIR}/pjlib/include/pj/compat/os_auto.h"
check_define() {
    local macro="$1" hint="$2"
    if [ ! -f "${OS_AUTO}" ] || ! grep -Eq "#[[:space:]]*define[[:space:]]+${macro}[[:space:]]+1" "${OS_AUTO}"; then
        warn "${macro}=1 não encontrado em os_auto.h — ${hint}"
    fi
}
check_define PJ_HAS_SSL_SOCK        "instale libssl-dev (TLS desativado)"
check_define PJMEDIA_HAS_OPUS_CODEC "instale libopus-dev (Opus desativado)"
check_define PJMEDIA_HAS_BCG729     "instale libbcg729-dev (G.729 desativado)"

# Recursos definidos como CFLAGS em build.mak (não entram no os_auto.h)
if [ -f build.mak ]; then
    for k in \
        PJMEDIA_HAS_VPX_CODEC \
        PJMEDIA_HAS_OPENH264_CODEC \
        PJMEDIA_HAS_FFMPEG_CODEC \
        PJNATH_HAS_UPNP; do
        grep -q "${k}=1" build.mak \
            || warn "${k}=1 não encontrado em build.mak — recurso pode ter sido desativado"
    done
    grep -q "libsamplerate" build.mak \
        || warn "resample via libsamplerate não detectado (instale libsamplerate0-dev)"
fi

# ----------------------------------------------------------------------------
step "8. Compilação e instalação da base do PJSIP"
make dep
make -j"${JOBS}"
make install
[ -e "${INSTALL_PREFIX}/lib/libpjsua2.so" ] || die "libpjsua2.so não instalada em ${INSTALL_PREFIX}/lib"

# ----------------------------------------------------------------------------
step "9. Binding pjsua2 (SWIG) compilado com o Python DO VENV"
# O Makefile usa PYTHON_EXE=python3 por padrão (system python!) — obrigatório
# sobrescrever, senão o binding sai para a versão errada do Python.
PYBIND="${PJSIP_DIR}/pjsip-apps/src/swig/python"
[ -d "${PYBIND}" ] || die "Diretório SWIG não encontrado: ${PYBIND}"
cd "${PYBIND}"

export PYTHONPATH=""   # evita contaminação de módulos
# GEN_DOC: pjproject 2.17 usa doxygen no SWIG; sem doxygen instalado o build
# falharia. USE_THREADS=-DSWIG_NO_EXPORT_ITERATOR_METHODS evita erro com SWIG 4.2+.
make PYTHON_EXE="${VENV_PY}" GEN_DOC= USE_THREADS=-threads

BINDING_SO="$(find "${PYBIND}/build" -name '_pjsua2*.so' -print -quit 2>/dev/null || true)"
[ -n "${BINDING_SO}" ] || die "Binding não gerado em ${PYBIND}/build"
[ -f "${PYBIND}/pjsua2.py" ] || die "pjsua2.py não gerado em ${PYBIND}"

# ----------------------------------------------------------------------------
step "10. Instalação do binding: .venv + third_party/pjsip-dist"
SITE_DIR="$("${VENV_PY}" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
SO_NAME="$(basename "${BINDING_SO}")"
mkdir -p "${SITE_DIR}" "${INSTALL_PREFIX}" "${PJSIP_DIR}/python"

# 1) .venv  → `import pjsua2` direto (testes, scripts)
install -m 0644 "${PYBIND}/pjsua2.py" "${SITE_DIR}/pjsua2.py"
install -m 0755 "${BINDING_SO}"       "${SITE_DIR}/${SO_NAME}"
# 2) third_party/pjsip-dist → layout usado pelo sip_backend.py e build_exe.sh
install -m 0644 "${PYBIND}/pjsua2.py" "${INSTALL_PREFIX}/pjsua2.py"
install -m 0755 "${BINDING_SO}"       "${INSTALL_PREFIX}/${SO_NAME}"
# 3) third_party/pjsip-opus-g729/python → primeiro caminho que o sip_backend
#    insere no sys.path; manter aqui evita que um binding antigo o sombreie.
install -m 0644 "${PYBIND}/pjsua2.py" "${PJSIP_DIR}/python/pjsua2.py"
install -m 0755 "${BINDING_SO}"       "${PJSIP_DIR}/python/${SO_NAME}"
log "binding: ${SITE_DIR}/${SO_NAME}"
log "binding: ${INSTALL_PREFIX}/${SO_NAME}"
log "binding: ${PJSIP_DIR}/python/${SO_NAME}"

# rpath portátil: $ORIGIN cobre o bundle do build_exe.sh (libs achatadas ao
# lado do binding) e o diretório third_party/pjsip-dist/lib; o caminho
# absoluto cobre as cópias que ficam no site-packages e na fonte.
log "Ajustando rpath (\$ORIGIN + ${INSTALL_PREFIX}/lib)..."
for so in "${SITE_DIR}/${SO_NAME}" "${INSTALL_PREFIX}/${SO_NAME}" "${PJSIP_DIR}/python/${SO_NAME}"; do
    patchelf --set-rpath "\$ORIGIN/lib:\$ORIGIN:${INSTALL_PREFIX}/lib" "$so"
done
# libs: irmãs no mesmo diretório (bundle e source run)
while IFS= read -r -d '' lib; do
    patchelf --set-rpath "\$ORIGIN:${INSTALL_PREFIX}/lib" "${lib}"
done < <(find "${INSTALL_PREFIX}/lib" -maxdepth 1 -type f -name '*.so*' -print0)

# ----------------------------------------------------------------------------
step "11. Prova-final: import + versão do módulo instalado no venv"
"${VENV_PY}" - <<'PY'
import sys
import pjsua2 as pj
print("python :", sys.executable)
print("pjsua2 OK, arquivo:", pj.__file__)
print("pjsua2 getattr(Endpoint):", hasattr(pj, "Endpoint"))
PY

log "Concluído."
log "Ative o venv:     source ${VENV_DIR}/bin/activate"
log "Rode o app:       ${VENV_PY} ${SCRIPT_DIR}/softphone.py"
log "Teste os codecs:  ${VENV_PY} ${SCRIPT_DIR}/test_pjsua2_codecs.py"
log "Empacote:         ${SCRIPT_DIR}/build_exe.sh"
