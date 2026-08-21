import pytest


def _have_pjsua2():
    try:
        import pjsua2  # noqa: F401
        return True
    except Exception:
        return False


def test_models_importable_when_pjsua2_present():
    if not _have_pjsua2():
        pytest.skip("pjsua2 indisponivel neste ambiente")
    import pjsua2 as pj

    from voice_neves.pjsip_models import MyAccount, MyBuddy, MyCall
    assert issubclass(MyAccount, pj.Account)
    assert issubclass(MyBuddy, pj.Buddy)
    assert issubclass(MyCall, pj.Call)


def test_models_build_sip_target_used():
    """Garante que pjsip_models importa build_sip_target do pacote (sem ImportError)."""
    if not _have_pjsua2():
        pytest.skip("pjsua2 indisponivel neste ambiente")
    import voice_neves.pjsip_models as m  # deve importar sem erros
    assert hasattr(m, "MyAccount")
