"""Singletons de runtime (cofre de senhas)."""
from .secrets_store import SecretsStore

secrets = SecretsStore()
