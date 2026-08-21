"""Ponto de entrada do Voice Neves.

Importa a UI por dentro de main() para que setup_logging() rode antes da
construcao do SecretsStore (runtime).
"""
import os
import tkinter as tk

from .utils import setup_logging


def main():
    setup_logging()
    # Import tardio: so agora o runtime (SecretsStore) e a UI (pjsua2) sao
    # carregados, com o logging ja configurado.
    from .app import SoftphoneApp
    root = tk.Tk(className="Voiceneves")
    app = SoftphoneApp(root)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()
    # Threads de audio/pjsua podem manter o interpretador vivo apos o
    # mainloop; encerra de vez para nao sobrar processo invisivel.
    os._exit(0)


if __name__ == "__main__":
    main()
