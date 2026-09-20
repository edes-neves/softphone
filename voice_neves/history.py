"""Historico de chamadas (I/O JSON, camada pura)."""
import json
import logging
import os
import tempfile

from .constants import DATA_DIR, HISTORY_FILE


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return [
            h for h in data
            if isinstance(h, dict) and isinstance(h.get("ts"), str) and isinstance(h.get("label"), str)
        ]
    except Exception as e:
        logging.error("Erro ao ler histórico (%s); usando vazio", e)
        return []



def save_history(history):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        # Escrita atômica: grava em arquivo temporário no mesmo diretório e
        # troca por os.replace — interromper o processo no meio nunca corrompe
        # o history.json (mesmo padrão de contacts.json/config).
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, prefix=".history-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, HISTORY_FILE)
            tmp_path = None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
    except OSError as e:
        logging.error("Falha ao gravar histórico: %s", e)


# =========================
# CONTATOS
# =========================
