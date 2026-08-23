"""Testes do sip_backend: probe de pjsua2 (True em Linux, False em Win/Mac sim)."""
import importlib
import sys


from voice_neves import sip_backend


def test_pjsua2_available_returns_bool():
    """No dev (com pjsua2) é True; em Win/Mac (sem pjsua2) é False. Não assume valor."""
    assert isinstance(sip_backend.pjsua2_available(), bool)


def test_import_pjsua2_module_or_none_consistency():
    pj = sip_backend.import_pjsua2()
    if sip_backend.pjsua2_available():
        assert pj is not None
    else:
        assert pj is None


def test_backend_label_string():
    label = sip_backend.backend_label()
    assert isinstance(label, str)
    assert "pjsua2" in label or "nenhum" in label


def test_import_pjsua2_no_raise_when_missing(monkeypatch):
    """Simula Win/Mac: pjsua2 inexiste -> import_pjsua2() deve retornar None, não lançar.

    Estratégia: setar sys.modules['pjsua2'] = None, o que faz 'import pjsua2'
    lançar Importerror (comportamento padrão do Python). importlib.reload garante
    estado isolado e restaurável.
    """
    old = sys.modules.get("pjsua2")
    monkeypatch.setitem(sys.modules, "pjsua2", None)
    try:
        importlib.reload(sip_backend)
        assert sip_backend.import_pjsua2() is None
        assert sip_backend.pjsua2_available() is False
    finally:
        if old is None:
            sys.modules.pop("pjsua2", None)
        else:
            sys.modules["pjsua2"] = old
        importlib.reload(sip_backend)  # restaura estado real
