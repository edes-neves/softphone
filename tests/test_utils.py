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


def test_parse_mwi_count_with_new_messages():
    body = (
        "Message-Account: sip:mailbox@pbx.x\n"
        "Messages-Waiting: yes\n"
        "Voice-Message: 2/5 (0/0)\n"
    )
    assert utils.parse_mwi_count(body) == 2


def test_parse_mwi_count_no_new_messages():
    body = (
        "Message-Account: sip:mailbox@pbx.x\n"
        "Messages-Waiting: no\n"
        "Voice-Message: 0/5 (0/0)\n"
    )
    assert utils.parse_mwi_count(body) == 0


def test_parse_mwi_count_waiting_no_without_voice():
    assert utils.parse_mwi_count("Messages-Waiting: no\n") == 0


def test_parse_mwi_count_no_body_returns_none():
    assert utils.parse_mwi_count("") is None
    assert utils.parse_mwi_count(None) is None


def test_parse_mwi_count_unrelated_body_returns_none():
    assert utils.parse_mwi_count("sip:3000\nContent-Type: application/sdp\n") is None


def test_parse_mwi_count_ignores_case_and_whitespace():
    body = "MESSAGES-WAITING: YES\n  voice-message : 1 / 3  \n"
    assert utils.parse_mwi_count(body) == 1


def test_extract_sip_identity_plain():
    assert utils.extract_sip_identity("sip:3000@pbx;transport=udp") == (None, "3000")
    assert utils.extract_sip_identity("sip:3000@pbx") == (None, "3000")
    assert utils.extract_sip_identity("3000") == (None, "3000")


def test_extract_sip_identity_with_display_name():
    # "From" com caller ID: '"João" <sip:3000@pbx>'
    assert utils.extract_sip_identity('"João" <sip:3000@pbx;user=phone>') == ("João", "3000")
    assert utils.extract_sip_identity("João <sip:3000@pbx>") == ("João", "3000")


def test_extract_sip_identity_invalid():
    assert utils.extract_sip_identity("") == (None, None)
    assert utils.extract_sip_identity("sip:@host") == (None, None)
    assert utils.extract_sip_identity("sip:unknown@host") == (None, None)
    assert utils.extract_sip_identity(None) == (None, None)


def test_extract_sip_identity_keeps_plus():
    assert utils.extract_sip_identity("sip:+5511999999999@pbx") == (None, "+5511999999999")
