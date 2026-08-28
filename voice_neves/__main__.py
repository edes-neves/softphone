"""Ponto de entrada do Voice Neves.

Importa a UI por dentro de main() para que setup_logging() rode antes da
construcao do SecretsStore (runtime).
"""
import os
import sys

from .utils import setup_logging


def main():
    setup_logging()
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
