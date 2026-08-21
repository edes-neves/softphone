"""Contatos locais em contacts.json (camada pura)."""
import json
import logging
import os

from .constants import CONTACTS_FILE, DATA_DIR


class ContactsStore:
    """Contatos em contacts.json (mesmo padrão de history.json)."""

    def __init__(self, path=CONTACTS_FILE):
        self.path = path

    def load(self):
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logging.error("Erro ao ler contatos (%s); usando vazio", e)
            return []
        if not isinstance(data, list):
            return []
        out = []
        for c in data:
            if isinstance(c, dict) and isinstance(c.get("name"), str) and isinstance(c.get("number"), str):
                out.append(
                    {
                        "name": c["name"].strip(),
                        "number": c["number"].strip(),
                        "server": str(c.get("server") or "").strip(),
                        "favorite": bool(c.get("favorite")),
                        "ringtone": str(c.get("ringtone") or "").strip(),
                        "monitor_presence": bool(c.get("monitor_presence")),
                    }
                )
        return out

    def save(self, contacts):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(contacts, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logging.error("Falha ao gravar contatos: %s", e)


