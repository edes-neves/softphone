import os

from voice_neves import constants as C
from voice_neves import utils


def test_clean_extension_removes_invalid_and_spaces():
    assert utils.clean_extension("  3000  ") == "3000"
    assert utils.clean_extension("joão+1") == "joo+1"  # não-ASCII removido; + é válido
    assert utils.clean_extension("a-b_c.d+e*f#") == "a-b_c.d+e*f#"
    assert utils.clean_extension(None) == ""
    assert utils.clean_extension("😊123") == "123"
    assert utils.clean_extension("a b") == "ab"  # espaços removidos


def test_is_valid_extension():
    assert utils.is_valid_extension("3000")
    assert utils.is_valid_extension("ramal.1")
    assert not utils.is_valid_extension("a b")
    assert not utils.is_valid_extension("")
    assert not utils.is_valid_extension("ramo;")

def test_is_valid_server():
    assert utils.is_valid_server("10.0.0.1")
    assert utils.is_valid_server("pbx.empresa.com.br:5060")
    assert not utils.is_valid_server("pbx ex com")
    assert not utils.is_valid_server("")


def test_build_sip_target():
    assert utils.build_sip_target("3000", "pbx.x") == "sip:3000@pbx.x"
    assert utils.build_sip_target("sip:3000@pbx.x", "") == "sip:3000@pbx.x"
    assert utils.build_sip_target("3000@pbx.x", "") == "sip:3000@pbx.x"
    assert utils.build_sip_target("", "pbx.x") == ""
    assert utils.build_sip_target("3000", "") == ""


def test_as_bool():
    assert utils._as_bool(True) is True
    assert utils._as_bool("true") is True
    assert utils._as_bool("YES") is True
    assert utils._as_bool(1) is True
    assert utils._as_bool(False) is False
    assert utils._as_bool(None) is False
    assert utils._as_bool("nope") is False
    assert utils._as_bool(0) is False


def test_is_wayland_env(monkeypatch):
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert utils.is_wayland() is False
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert utils.is_wayland() is True


def test_appindicator_available_returns_bool():
    assert isinstance(utils.appindicator_available(), bool)


def test_resource_path_resolves_to_project_root():
    p = utils.resource_path("Icone.png")
    # resolve a partir da raiz do projeto (parent do pacote)
    assert p.endswith("Icone.png")
    assert os.path.isfile(p)  # Icone.png existe na raiz do repo


def test_constants_paths_are_strings():
    assert isinstance(C.CONFIG_DIR, str)
    assert isinstance(C.DATA_DIR, str)
    assert isinstance(C.CONFIG_FILE, str)
    assert C.CONFIG_FILE.startswith(C.CONFIG_DIR)


def test_constants_regex():
    assert C.EXT_RE.match("3000")
    assert C.SERVER_RE.match("host:5060")
    assert not C.EXT_RE.match("a b")
