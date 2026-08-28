"""Voice Neves - softphone SIP (pjsua2 + Qt/PySide6).

A camada pura (constants, utils, config, history, secrets_store,
contacts_store, ldap_manager, themes) nao depende de Qt/PySide6 nem de pjsua2 e
e testavel isoladamente. A UI e o controlador ficam em `app`; o ponto de
entrada em `__main__`.
"""
__version__ = "1.1.3"

__all__ = ["__version__"]
