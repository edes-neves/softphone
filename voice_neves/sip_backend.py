"""Detecção de backend SIP.

Hoje apenas pjsua2 (build Linux com G.729/BCG729 embutido). O app já possui
ganchos para um futuro backend alternativo em Win/Mac -- basta implementar
`import_sip()` com um novo binding (pjsua2 cross-compiled, ou `linphone-sdk`
pip-installável, que traz Opus/PCMA/PCMU em vez de G.729).

Sem abstração prematura: este módulo só PROBE. O código que usa `pj.*` está
travado em init_pjsip()/register_account()/make_call() e friends, todos
cercados por `if self._sip_available` em app.py. Adicionar um segundo backend
futuro é um trabalho separado (interface genial da camada de mídia).
"""
import logging


def pjsua2_available():
    """True se pjsua2 for importável nesta plataforma (build Linux)."""
    try:
        import pjsua2  # noqa: F401
        return True
    except Exception:
        return False


def import_pjsua2():
    """Retorna o módulo pjsua2, ou None se indisponível (não lança)."""
    try:
        import pjsua2 as pj
        return pj
    except Exception as e:
        logging.warning("pjsua2 indisponível neste sistema (esperado em Win/Mac): %s", e)
        return None


def backend_label():
    """Texto curto para tooltips/status indicando o backend ativo."""
    if pjsua2_available():
        return "pjsua2 (Linux/BCG729)"
    return "nenhum (build atual só suporta SIP no Linux)"
