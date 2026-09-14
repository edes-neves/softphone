"""Detecção de backend SIP.

Backends conhecidos (em ordem de preferência):

1. ``pjsua2``        — binding SWIG do PJSIP. Traz todo o conjunto de
                       codecs (incl. G.729/BCG729, Opus, H.264, VP8/VP9)
                       + SRTP + vídeo + TLS.
                       Em Linux: compilado via build_pjsip.sh
                       Em Windows: compilado via build_pjsip_win.ps1
2. ``linphone``      — SDK do Linphone (Windows/macOS), quando instalado.
                       Traz Opus/PCMU/PCMA (SEM G.729).

ATENÇÃO (importante ler antes de plugar um 2º backend):
O ``app.py`` usa a API do pjsua2 **diretamente** em dezenas de pontos
(~73 usos de ``pj.*``: Endpoint, AudioMedia, CallOpParam, PresenceStatus,
SipHeader, constantes PJSIP_INV_STATE_*, AudioMediaPlayer, etc.). Por isso,
trocar de backend NÃO é plugar aqui dentro: é **reescrever a camada de mídia**
do app. Este módulo apenas PROBE e expõe qual binding está ativo.
"""
import logging
import os
import sys


def _add_local_pjsip_paths():
    """Adiciona ao sys.path os diretórios locais do pjsua2 compilado.

    No Windows e Linux, o pjsua2 pode estar compilado em:
      - third_party/pjsip-win/python  (Windows build)
      - third_party/pjsip-opus-g729/python  (Linux build)
      - third_party/pjsip-dist (distribuição pré-compilada)

    Também adiciona o diretório raiz do projeto para DLLs no Windows.
    """
    # Diretório raiz do projeto (onde está voice_neves/)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Candidatos para diretórios de Python binding
    candidates = [
        os.path.join(project_root, "third_party", "pjsip-win", "python"),
        os.path.join(project_root, "third_party", "pjsip-opus-g729", "python"),
        os.path.join(project_root, "third_party", "pjsip-dist"),
    ]

    for path in candidates:
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)
            logging.debug("pjsip: adicionado ao sys.path: %s", path)

    # No Windows, adicionar o diretório de lib para encontrar DLLs
    if os.name == "nt":
        lib_dirs = [
            os.path.join(project_root, "third_party", "pjsip-win", "lib"),
            os.path.join(project_root, "third_party", "pjsip-dist", "lib"),
            project_root,  # DLLs podem estar na raiz
        ]
        for lib_path in lib_dirs:
            if os.path.isdir(lib_path) and lib_path not in sys.path:
                sys.path.insert(0, lib_path)
                # Também adicionar ao PATH do sistema para DLLs
                os.environ["PATH"] = lib_path + os.pathsep + os.environ.get("PATH", "")
                logging.debug("pjsip: adicionado ao PATH: %s", lib_path)


# Executa antes de tentar importar
_add_local_pjsip_paths()


# Tenta importar no máximo um binding. Ordem = preferência.
def _load_backend():
    for name in ("pjsua2", "linphone"):
        try:
            module = __import__(name)
            # Se o módulo carrega mas não tem o atributo canônico, ignora.
            marker = "linphone" if name == "linphone" else "Endpoint"
            if hasattr(module, marker) or marker in vars(module):
                logging.info("Backend SIP carregado: %s", name)
                return module
        except Exception as e:
            logging.debug("Backend %s indisponível: %s", name, e)
    return None


_MODULE = _load_backend()


def sip_available():
    """True se algum backend SIP estiver importável."""
    return _MODULE is not None


def current_backend():
    """Nome do binding SIP ativo ('pjsua2', 'linphone') ou None."""
    if _MODULE is None:
        return None
    return "pjsua2" if hasattr(_MODULE, "Endpoint") else "linphone"


def import_sip():
    """Retorna o módulo do backend SIP ativo, ou None (não lança)."""
    return _MODULE


def pjsua2_available():
    """True se o backend atual for o pjsua2."""
    return current_backend() == "pjsua2"


def import_pjsua2():
    """Compat: devolve o módulo pjsua2 só se ele for o ativo. Senão None."""
    return _MODULE if current_backend() == "pjsua2" else None


def backend_label():
    """Texto curto para tooltips/status indicando o backend ativo."""
    name = current_backend()
    if name == "pjsua2":
        if sys.platform == "win32":
            return "pjsua2 (Windows/Opus)"
        return "pjsua2 (Linux/BCG729)"
    if name == "linphone":
        return "linphone (Win/Mac, sem G.729)"
    return "nenhum (backend SIP não detectado)"
