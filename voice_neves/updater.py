"""Atualização automática: checa versão remota e baixa o novo binário.

Camada pura/testável para a lógica de versionamento e download; a aplicação do
binário é feita de forma conservadora (baixar, validar checksum e informar o
usuário para reiniciar), evitando corromper o binário em execução.

Formato do version.json servido (idealmente junto do provisioning):

    {
      "version": "1.1.0",
      "url": "https://meuservidor/downloads/VoiceNeves-1.1.0.AppImage",
      "sha256": "<hex>",
      "url_linux": "https://meuservidor/downloads/VoiceNeves-1.1.0.AppImage",
      "sha256_linux": "<hex>",
      "url_win": "https://meuservidor/downloads/VoiceNeves-1.1.0.exe",
      "sha256_win": "<hex>"
    }

`url`/`sha256` são o fallback genérico. As chaves `url_linux`/`sha256_linux`
e `url_win`/`sha256_win` permitem oferecer binários diferentes por plataforma
(ex.: AppImage no Linux e .exe no Windows) com o mesmo version.json.

Se `sha256` estiver presente, o download é validado antes de ser considerado
pronto para aplicar.
"""
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request

__all__ = [
    "parse_version_info",
    "fetch_version_info",
    "is_newer",
    "download_to_temp",
    "download_to_downloads",
    "default_download_dir",
    "downloads_dir",
    "DownloadCanceled",
    "sha256_file",
    "Updater",
]


from .platform import downloads_dir  # noqa: E402  (compat: repo antigo expunha via updater)


class DownloadCanceled(Exception):
    """Cancelamento de download solicitado pelo usuário."""


# Versão padrão lida do módulo de constantes em runtime (evita import circular).
def current_version():
    try:
        from .constants import APP_VERSION

        return APP_VERSION
    except Exception:
        return "0.0.0"


def default_download_dir():
    """Pasta Downloads do usuário (~/Downloads; XDG_DOWNLOAD_DIR no Linux)."""
    from .platform import downloads_dir

    return downloads_dir()


def _is_windows():
    """True quando a plataforma atual é Windows."""
    return sys.platform.startswith("win")


def _resolve_platform_artifact(raw):
    """Escolhe url/sha256 conforme a plataforma atual.

    Em Windows prioriza ``url_win`` (e ``sha256_win``); nas demais plataformas
    (Linux/macOS) prioriza ``url_linux`` (e ``sha256_linux``). Quando a chave
    específica não existe, volta para o par genérico ``url``/``sha256``.
    """
    if _is_windows():
        url = str(raw.get("url_win") or "").strip()
        if url:
            return url, str(raw.get("sha256_win") or "").strip().lower()
        url = str(raw.get("url_windows") or "").strip()
        if url:
            return url, str(raw.get("sha256_windows") or "").strip().lower()
    else:
        url = str(raw.get("url_linux") or "").strip()
        if url:
            return url, str(raw.get("sha256_linux") or "").strip().lower()
    return str(raw.get("url") or "").strip(), str(raw.get("sha256") or "").strip().lower()


def parse_version_info(raw):
    """Valida um payload de version.json."""
    if not isinstance(raw, dict):
        raise ValueError("Payload de versão inválido")
    version = str(raw.get("version") or "").strip()
    if not version:
        raise ValueError("version.json sem 'version'")
    url, sha256 = _resolve_platform_artifact(raw)
    if not url:
        raise ValueError("version.json sem 'url'")
    return {
        "version": version,
        "url": url,
        "sha256": sha256,
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


def _download(url, dest_dir, on_progress=None, cancel_cb=None, timeout=60, auth_user="", auth_pass=""):
    """Baixa `url` para `dest_dir` em `nome.partial` e renomeia para `nome`.

    `on_progress(downloaded, total)` é chamado a cada bloco (total pode ser
    `None` quando o servidor não informa Content-Length). Se `cancel_cb()`
    retornar True, o download é abortado, o `.partial` é removido e
    `DownloadCanceled` é levantado.
    """
    req = urllib.request.Request(url)
    if auth_user:
        import base64

        token = base64.b64encode(f"{auth_user}:{auth_pass}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    name = os.path.basename(urllib.parse.urlparse(url).path) or "update.bin"
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{name}.partial")
    canceled = False
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
            headers = getattr(resp, "headers", None)
            total = None
            try:
                if headers is not None:
                    total = int(headers.get("Content-Length") or 0) or None
            except (TypeError, ValueError):
                total = None
            if on_progress is not None:
                on_progress(0, total)
            done = 0
            while True:
                if cancel_cb is not None and cancel_cb():
                    canceled = True
                    break
                block = resp.read(1 << 20)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if on_progress is not None:
                    on_progress(done, total)
    finally:
        if canceled:
            try:
                os.remove(dest)
            except OSError:
                pass
            raise DownloadCanceled()
    # Remove o sufixo ".partial" para um nome de arquivo limpo.
    final = os.path.splitext(dest)[0]
    try:
        os.replace(dest, final)
    except OSError:
        final = dest
    return final


def download_to_temp(url, dest_dir=None, timeout=60, auth_user="", auth_pass=""):
    """Baixa o artefato para um diretório temporário e retorna o caminho."""
    import tempfile

    dest_dir = dest_dir or tempfile.gettempdir()
    return _download(
        url,
        dest_dir,
        on_progress=None,
        cancel_cb=None,
        timeout=timeout,
        auth_user=auth_user,
        auth_pass=auth_pass,
    )


def download_to_downloads(url, on_progress=None, cancel_cb=None, timeout=60, auth_user="", auth_pass=""):
    """Baixa o artefato para a pasta Downloads do usuário, com progresso."""
    return _download(
        url,
        default_download_dir(),
        on_progress=on_progress,
        cancel_cb=cancel_cb,
        timeout=timeout,
        auth_user=auth_user,
        auth_pass=auth_pass,
    )


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

    def download(self, on_progress=None, cancel_cb=None, timeout=60, auth_user="", auth_pass=""):
        """Baixa e valida o artefato para a pasta Downloads; retorna o caminho.

        `on_progress(downloaded, total)` é chamado durante o download e
        `cancel_cb()` (retornando True) aborta a operação com
        `DownloadCanceled`.
        """
        if self.latest is None:
            raise RuntimeError("Nenhuma atualização checada ainda")
        path = download_to_downloads(
            self.latest["url"],
            on_progress=on_progress,
            cancel_cb=cancel_cb,
            timeout=timeout,
            auth_user=auth_user,
            auth_pass=auth_pass,
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
        self.downloaded_path = path
        return path
