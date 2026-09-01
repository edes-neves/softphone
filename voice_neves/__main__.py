"""Ponto de entrada do Voice Neves.

Importa a UI por dentro de main() para que setup_logging() rode antes da
construcao do SecretsStore (runtime).
"""
import os
import sys

from .utils import setup_logging


def _prefer_xwayland():
    """Em sessao Wayland com XWayland disponivel, roda em X11 (xcb).

    O renderer de video do PJSIP/SDL so funciona de forma estavel embutido via
    X11. No Wayland nativo uma janela SDL propria congela o loop do Qt. Quando
    a sessao e Wayland mas ha um display X (XWayland) alcancavel, forcar o QPA
    xcb -- antes do QApplication -- para a pre�via embutir sem travar. Nao
    sobrescreve uma escolha explicita do usuario (var de ambiente ja definida).
    """
    import logging

    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session != "wayland" and not os.environ.get("WAYLAND_DISPLAY"):
        return
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    display = os.environ.get("DISPLAY")
    if not display:
        return
    sock = f"/tmp/.X11-unix/X{display.rsplit(':', 1)[-1].split('.', 1)[0]}"
    if not os.path.exists(sock):
        return
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    logging.info("Sessao Wayland com XWayland; usando QPA xcb para video estavel")


def main():
    setup_logging()
    _prefer_xwayland()
    # Import tardio: so agora o runtime (SecretsStore) e a UI (pjsua2) sao
    # carregados, com o logging ja configurado.
    from PySide6.QtWidgets import QApplication

    from .app import SoftphoneApp

    qapp = QApplication(sys.argv)
    qapp.setApplicationName("VoiceNeves")
    qapp.setApplicationDisplayName("Voice Neves")
    app = SoftphoneApp(qapp)
    app.show()
    rc = qapp.exec()
    # Threads de audio/pjsua podem manter o interpretador vivo apos o
    # mainloop; encerra de vez para nao sobrar processo invisivel.
    os._exit(rc)


if __name__ == "__main__":
    main()
