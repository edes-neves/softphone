"""Atualização automática: checa versão remota e baixa o novo binário.

Camada pura/testável para a lógica de versionamento e download; a aplicação do
binário é feita de forma conservadora (baixar para /tmp, validar checksum e
informar o usuário para reiniciar), evitando corromper o binário em execução.

Formato do version.json servido (idealmente junto do provisioning):

    {
      "version": "1.1.0",
      "url": "https://meuservidor/downloads/VoiceNeves-1.1.0.AppImage",
      "sha256": "<hex>"
    }

Se `sha256` estiver presente, o download é validado antes de ser considerado
pronto para aplicar.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

__all__ = [
    "parse_version_info",
    "fetch_version_info",
    "is_newer",
    "download_to_temp",
    "sha256_file",
    "Updater",
]


# Versão padrão lida do módulo de constantes em runtime (evita import circular).
def current_version():
    try:
        from .constants import APP_VERSION

        return APP_VERSION
    except Exception:
        return "0.0.0"


def parse_version_info(raw):
    """Valida um payload de version.json."""
    if not isinstance(raw, dict):
        raise ValueError("Payload de versão inválido")
    version = str(raw.get("version") or "").strip()
    url = str(raw.get("url") or "").strip()
    if not version or not url:
        raise ValueError("version.json sem 'version' ou 'url'")
    return {
        "version": version,
        "url": url,
        "sha256": str(raw.get("sha256") or "").strip().lower(),
    }


def fetch_version_info(url, timeout=10, auth_user="", auth_pass=""):
    """Baixa e valida um version.json da URL remota."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if auth_user:
        import base64

        token = base64.b64encode(f"{auth_user}:{auth_pass}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    return parse_version_info(raw)


def parse_version(version):
    """Converte '1.2.3' (ou 'v1.2.3') em tupla de inteiros para comparação."""
    v = str(version or "").strip().lstrip("vV")
    parts = []
    for seg in v.split(".")[:4]:
        digits = "".join(ch for ch in seg if ch.isdigit())
        if not digits:
            parts.append(0)
        else:
            parts.append(int(digits))
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def is_newer(remote_version, local_version):
    """True se a versão remota é estritamente mais nova que a local."""
    return parse_version(remote_version) > parse_version(local_version)


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def download_to_temp(url, dest_dir=None, timeout=60, auth_user="", auth_pass=""):
    """Baixa o artefato para um diretório temporário e retorna o caminho."""
    import tempfile

    dest_dir = dest_dir or tempfile.gettempdir()
    req = urllib.request.Request(url)
    if auth_user:
        import base64

        token = base64.b64encode(f"{auth_user}:{auth_pass}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    name = os.path.basename(urllib.parse.urlparse(url).path) or "update.bin"
    dest = os.path.join(dest_dir, f"{name}.partial")
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
        while True:
            block = resp.read(1 << 20)
            if not block:
                break
            out.write(block)
    return dest


class Updater:
    """Estado da atualização: resultado de checagem e download aplicável."""

    def __init__(self, local_version=None):
        self.local_version = local_version or current_version()
        self.latest = None  # dict do parse_version_info mais recente
        self.downloaded_path = None
        self.last_check = 0.0

    def check(self, url, auth_user="", auth_pass="", timeout=10):
        """Checa a versão remota. Retorna True se existe atualização disponível."""
        info = fetch_version_info(url, timeout, auth_user, auth_pass)
        self.latest = info
        self.last_check = time.time()
        return is_newer(info["version"], self.local_version)

    def download(self, timeout=60, auth_user="", auth_pass=""):
        """Baixa e valida o artefato; retorna o caminho local pronto."""
        if self.latest is None:
            raise RuntimeError("Nenhuma atualização checada ainda")
        path = download_to_temp(
            self.latest["url"], timeout=timeout, auth_user=auth_user, auth_pass=auth_pass
        )
        if self.latest.get("sha256"):
            actual = sha256_file(path)
            if actual != self.latest["sha256"]:
                try:
                    os.remove(path)
                except OSError:
                    pass
                raise ValueError(
                    f"Checksum inválido: esperado {self.latest['sha256']}, obtido {actual}"
                )
        # Remove o sufixo ".partial" para um nome de arquivo limpo.
        final = os.path.splitext(path)[0]  # tira ".partial"
        try:
            os.replace(path, final)
        except OSError:
            final = path
        self.downloaded_path = final
        return final
