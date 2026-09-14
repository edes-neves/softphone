"""setup_pjsua2_win.py — Build da extensao _pjsua2 para Windows (MSVC).

Le PJDIR do ambiente (definido pelo build_pjsip_win.ps1), descobre todas as
bibliotecas .lib geradas pelo MSBuild e as liga a extensao SWIG _pjsua2.

Uso:
    set PJDIR=C:\\Users\\edesn\\dwhelper\\Softphone\\build\\pjproject
    python setup_pjsua2_win.py build_ext --inplace
"""
import glob
import os
import sys
from pathlib import Path

from setuptools import Extension, setup

pjdir = os.environ.get("PJDIR", "")
if not pjdir or not os.path.isdir(pjdir):
    sys.exit(
        f"ERRO: variavel PJDIR deve apontar para a raiz do pjproject. "
        f"Valor atual: {pjdir!r}"
    )


# ---------------------------------------------------------------------------
# Ler versao do PJSIP
# ---------------------------------------------------------------------------
def read_pj_version(pjproject_dir: str) -> str:
    env_version = os.environ.get("PJ_VERSION", "").strip()
    if env_version:
        return env_version

    version_file = Path(pjproject_dir) / "version.mak"
    values: dict[str, str] = {}
    for line in version_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("export PJ_VERSION_"):
            continue
        key, sep, value = line.partition(":=")
        if not sep:
            key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.replace("export", "").strip()
        values[key] = value.strip()

    major = values.get("PJ_VERSION_MAJOR", "")
    minor = values.get("PJ_VERSION_MINOR", "")
    rev = values.get("PJ_VERSION_REV", "")
    suffix = values.get("PJ_VERSION_SUFFIX", "")

    if not major or not minor:
        sys.exit(f"ERRO: nao foi possivel ler a versao do PJSIP em {version_file}")

    version = f"{major}.{minor}"
    if rev:
        version += f".{rev}"
    if suffix:
        version += suffix
    return version


pj_version = read_pj_version(pjdir)
print(f"[setup_pjsua2_win] PJDIR     = {pjdir}")
print(f"[setup_pjsua2_win] Versao    = {pj_version}")


# ---------------------------------------------------------------------------
# Diretorios de include
# ---------------------------------------------------------------------------
include_dirs = [
    os.path.join(pjdir, "pjlib", "include"),
    os.path.join(pjdir, "pjlib-util", "include"),
    os.path.join(pjdir, "pjmedia", "include"),
    os.path.join(pjdir, "pjsip", "include"),
    os.path.join(pjdir, "pjnath", "include"),
]

# Incluir terceiros (headers do Opus, OpenH264, etc.)
third_party_include = os.path.join(pjdir, "third_party", "include")
if os.path.isdir(third_party_include):
    include_dirs.append(third_party_include)

# ---------------------------------------------------------------------------
# Diretorios de busca de bibliotecas
# ---------------------------------------------------------------------------
lib_search_dirs = []
for d in [
    os.path.join(pjdir, "lib"),
    os.path.join(pjdir, "pjlib", "lib"),
    os.path.join(pjdir, "pjlib-util", "lib"),
    os.path.join(pjdir, "pjmedia", "lib"),
    os.path.join(pjdir, "pjsip", "lib"),
    os.path.join(pjdir, "pjnath", "lib"),
    os.path.join(pjdir, "third_party", "lib"),
]:
    if os.path.isdir(d):
        lib_search_dirs.append(d)

# ---------------------------------------------------------------------------
# Coletar todas as bibliotecas .lib geradas pelo MSBuild
# ---------------------------------------------------------------------------
libraries: list[str] = []
for d in lib_search_dirs:
    for f in sorted(glob.glob(os.path.join(d, "*.lib"))):
        lib_name = os.path.splitext(os.path.basename(f))[0]
        if lib_name not in libraries:
            libraries.append(lib_name)

print(f"[setup_pjsua2_win] Bibliotecas encontradas: {len(libraries)}")
for lib in libraries:
    print(f"  - {lib}")

# Bibliotecas do sistema Windows necessarias para PJSIP
system_libs = [
    "ws2_32",      # Winsock 2
    "ole32",       # COM
    "oleaut32",    # COM automation (Variants/BSTR p/ DirectShow)
    "winmm",       # Multimedia
    "dsound",      # DirectSound
    "dxguid",      # DirectX GUIDs
    "mswsock",     # Microsoft Winsock
    "advapi32",    # Security/Registry
    "user32",      # User interface
    "iphlpapi",    # IP Helper
    "crypt32",     # Crypto API (para OpenSSL/TLS)
    "secur32",     # Security Support Provider
    "gdi32",       # GDI (video)
]

# Adicionar libs do sistema que nao estejam ja na lista
for slib in system_libs:
    if slib not in libraries:
        libraries.append(slib)

print(f"[setup_pjsua2_win] Total de bibliotecas: {len(libraries)}")

# ---------------------------------------------------------------------------
# Compilar extensao
# ---------------------------------------------------------------------------
swig_dir = os.path.join(pjdir, "pjsip-apps", "src", "swig", "python")
wrap_source = os.path.join(swig_dir, "pjsua2_wrap.cpp")

if not os.path.isfile(wrap_source):
    sys.exit(f"ERRO: pjsua2_wrap.cpp nao encontrado em {wrap_source}")

setup(
    name="pjsua2",
    version=pj_version,
    description="SIP User Agent Library based on PJSIP (Voice Neves Windows build)",
    url="http://www.pjsip.org",
    ext_modules=[
        Extension(
            "_pjsua2",
            sources=[wrap_source],
            include_dirs=include_dirs,
            library_dirs=lib_search_dirs,
            libraries=libraries,
            language="c++",
        )
    ],
    py_modules=["pjsua2"],
)
