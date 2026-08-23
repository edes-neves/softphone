"""Voice Neves - softphone SIP (pjsua2 + tkinter).

A camada pura (constants, utils, config, history, secrets_store,
contacts_store, ldap_manager, themes) nao depende de tkinter nem de pjsua2 e
e testavel isoladamente. A UI e o controlador ficam em `app`; o ponto de
entrada em `__main__`.
"""
__version__ = "1.0.4"

__all__ = ["__version__"]
