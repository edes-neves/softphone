"""Armazenamento seguro de senhas (keyring do sistema com fallback 0600)."""
import json
import logging
import os

from .constants import CONFIG_DIR, KEYRING_SERVICE, SECRETS_FILE


class SecretsStore:
    """Guarda senhas no keyring do sistema; cai para um arquivo 0600 se indisponível."""

    def __init__(self, service=KEYRING_SERVICE, fallback_file=SECRETS_FILE):
        self.service = service
        self.fallback_file = fallback_file
        self._keyring = None
        self._fallback = {}
        self._init()

    def _init(self):
        try:
            import keyring

            keyring.get_password(self.service, "_probe")
            self._keyring = keyring
        except Exception as e:
            logging.warning("Keyring indisponível (%s); usando arquivo de secrets local", e)
            self._keyring = None

        if os.path.exists(self.fallback_file):
            try:
                with open(self.fallback_file, encoding="utf-8") as f:
                    self._fallback = json.load(f) or {}
            except Exception as e:
                logging.warning("Falha ao ler secrets locais (%s); usando vazio", e)
                self._fallback = {}
        self._secure_file(self.fallback_file)

    @staticmethod
    def _secure_file(path):
        try:
            if os.path.exists(path):
                os.chmod(path, 0o600)
        except OSError as e:
            logging.warning("Não foi possível ajustar permissões de %s: %s", path, e)

    def get(self, key, default=None):
        if self._keyring is not None:
            try:
                value = self._keyring.get_password(self.service, key)
                if value is not None:
                    return value
            except Exception as e:
                logging.warning("Falha ao ler keyring (%s); usando fallback", e)
        return self._fallback.get(key, default)

    def set(self, key, value):
        if self._keyring is not None:
            try:
                self._keyring.set_password(self.service, key, value)
                return
            except Exception as e:
                logging.warning("Falha ao gravar keyring (%s); usando fallback", e)
        self._fallback[key] = value
        self._save_fallback()

    def delete(self, key):
        if self._keyring is not None:
            try:
                self._keyring.delete_password(self.service, key)
            except Exception:
                pass
        if key in self._fallback:
            del self._fallback[key]
            self._save_fallback()

    def _save_fallback(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(self.fallback_file, "w", encoding="utf-8") as f:
                json.dump(self._fallback, f, indent=2)
            self._secure_file(self.fallback_file)
        except OSError as e:
            logging.error("Falha ao gravar secrets locais: %s", e)


# =========================
# CONFIG
# =========================
