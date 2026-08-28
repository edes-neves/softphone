import json

from voice_neves.cti_api import parse_call_request


def test_parse_call_full():
    body = json.dumps({"number": "  3000  ", "server": "  pbx  "}).encode("utf-8")
    assert parse_call_request(body) == {"number": "3000", "server": "pbx"}


def test_parse_call_only_number():
    assert parse_call_request(b'{"number":"100"}') == {"number": "100", "server": None}


def test_parse_call_empty():
    assert parse_call_request(b"") == {"number": "", "server": None}
    assert parse_call_request(None) == {"number": "", "server": None}


def test_parse_call_string_input():
    assert parse_call_request('{"number": "200"}') == {"number": "200", "server": None}


def test_parse_call_invalid():
    assert parse_call_request(b"nao-e-json") is None
    assert parse_call_request(b'["lista"]') is None
