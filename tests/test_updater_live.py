"""Teste de integração (LIVE) do updater contra o repositório público.

Simula o que o app faz em produção: consulta o version.json público do GitHub
e confirma que a URL do AppImage aponta para um asset de release acessível.

Contato com a rede só ocorre quando LIVE_UPDATE_TEST=1. Por padrão o teste é
pulado, então o `pytest tests/` (CI, offline) continua rápido e confiável.

    LIVE_UPDATE_TEST=1 python -m pytest tests/test_updater_live.py -v

Falhas de rede resultam em skip (não quebram um run acidentalmente offline),
mas resposta HTTP de erro inesperada (ex.: 404 no AppImage) é reprovada.
"""
import os
import re
import urllib.error
import urllib.request

import pytest

from voice_neves import updater

# URL oficial do version.json do repositório público (fonte de verdade).
LIVE_URL = os.environ.get(
    "VOICENEVS_VERSION_JSON",
    "https://raw.githubusercontent.com/edes-neves/softphone/master/version.json",
)

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

pytestmark = pytest.mark.skipif(
    os.environ.get("LIVE_UPDATE_TEST") != "1",
    reason="teste de integração live: defina LIVE_UPDATE_TEST=1 para rodar",
)


def test_live_fetch_version_json_and_asset_accessible():
    try:
        info = updater.fetch_version_info(LIVE_URL, timeout=15)
    except Exception as e:  # noqa: BLE001 - rede indisponível => skip
        pytest.skip(f"sem acesso ao version.json público: {e}")

    assert info["version"], "version.json sem version"
    assert _SEMVER_RE.match(info["version"]), (
        f"versão '{info['version']}' não é SemVer (X.Y.Z)"
    )
    assert info["url"].startswith("https://"), f"URL inválida: {info['url']}"

    if info["sha256"]:
        assert _SHA256_RE.match(info["sha256"]), (
            f"sha256 não é um hex de 64 caracteres: {info['sha256']!r}"
        )

    # A URL do AppImage deve apontar para um asset de release público e
    # acessível. HEAD evita baixar os ~159 MB do binário.
    if "releases/download/" not in info["url"]:
        pytest.skip(f"URL não é de release do GitHub (mira módulo): {info['url']}")

    try:
        req = urllib.request.Request(info["url"], method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        pytest.fail(f"AppImage em {info['url']} retornou HTTP {e.code} (não deve 404/401)")
    except Exception as e:  # noqa: BLE001 - rede indisponível => skip
        pytest.skip(f"sem acesso ao asset do AppImage: {e}")

    assert status == 200, f"AppImage em {info['url']} retornou HTTP {status}"


def test_live_version_can_be_parsed_by_app():
    """O updater do app consegue comparar a versão publicada com a local."""
    try:
        info = updater.fetch_version_info(LIVE_URL, timeout=15)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"sem acesso ao version.json público: {e}")

    parts = updater.parse_version(info["version"])
    assert len(parts) == 4  # (maior, menor, patch, patch4)
    assert all(isinstance(p, int) for p in parts)
    # A versão publicada deve ser >= a desta build (monotônica).
    assert updater.is_newer(info["version"], updater.current_version()) or (
        updater.parse_version(info["version"]) == updater.parse_version(updater.current_version())
    ), f"{info['version']} < local {updater.current_version()}"
