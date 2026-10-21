"""Ponto de entrada do Voice Neves.

Importa a UI por dentro de main() para que setup_logging() rode antes da
construcao do SecretsStore (runtime).
"""
import logging
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
    # Desabilita a ponte AT-SPI do Qt para evitar segfault em distribuições
    # cujo GLib/at-spi é incompatível com o Qt embutido no AppImage.
    os.environ.setdefault("QT_LINUX_ACCESSIBILITY_ALWAYS_ON", "0")
    os.environ.setdefault("NO_AT_BRIDGE", "1")
    # Import tardio: so agora o runtime (SecretsStore) e a UI (pjsua2) sao
    # carregados, com o logging ja configurado.
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    from .app import SoftphoneApp

    qapp = QApplication(sys.argv)
    qapp.setApplicationName("VoiceNeves")
    qapp.setApplicationDisplayName("Voice Neves")

    # ---- Instancia unica ----
    # Se o app ja estiver rodando (mesmo minimizado na bandeja), a nova
    # execucao NAO abre outra instancia: apenas pede a janela existente para
    # reaparecer (maximizar/restaurar) e sai. Evita varios icones/processos.
    server_name = "VoiceNeves-single-instance"
    probe = QLocalSocket()
    probe.connectToServer(server_name)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        os._exit(0)

    # Nenhuma instancia ativa: se sobrou um socket orfao (ex.: crash anterior),
    # remove para poder escutar.
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    if not server.listen(server_name):
        logging.warning("Nao foi possivel criar o servidor de instancia unica: %s",
                        server.errorString())

    app = SoftphoneApp(qapp)

    def _on_second_instance():
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: c.readAll())
            conn.disconnected.connect(conn.deleteLater)
        app._show_window()

    server.newConnection.connect(_on_second_instance)

    app.show()
    rc = qapp.exec()
    # Threads de audio/pjsua podem manter o interpretador vivo apos o
    # mainloop; encerra de vez para nao sobrar processo invisivel. Antes,
    # esvazia todos os buffers de log/console: os._exit() nao roda os
    # registradores do interpreter (atexit, flush de stdout/stderr).
    logging.shutdown()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(rc)


if __name__ == "__main__":
    main()
