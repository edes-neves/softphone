"""Wrappers pjsua2: Account, Buddy, Call. Requer pjsua2 quando disponível.

Em plataformas sem pjsua2 (Win/Mac no build atual), as classes ficam como
`None` -- o importador não falha. As guardas em `app.py` evitam qualquer uso
nesses caso. Adicionar `pj.X` aqui é seguro: só roda quando `_HAS_PJSUA2`.
"""
import logging

try:
    import pjsua2 as pj
    _HAS_PJSUA2 = True
except Exception:
    pj = None
    _HAS_PJSUA2 = False

from .utils import build_sip_target  # noqa: E402

if _HAS_PJSUA2:

    class MyAccount(pj.Account):
        def __init__(self, app, data):
            super().__init__()
            self.app = app
            self.data = data

        def onRegState(self, prm):
            if prm.code == 200:
                status = "ONLINE"
            elif prm.code in (0, 100):
                status = "REGISTERING"
            else:
                status = "OFFLINE"
            logging.info(
                "Registro de %s@%s: código %s (%s)",
                self.data.get("user"),
                self.data.get("server"),
                prm.code,
                prm.reason or "sem motivo",
            )
            self.app._ui(self.app.update_account_status, self, status)
            if status == "OFFLINE":
                # Failover de servidor: o app tenta um servidor de backup
                # quando o registro no servidor ativo falha.
                self.app._ui(self.app._on_account_reg_failed, self)

        def onMwiInfo(self, prm):
            from .utils import parse_mwi_count

            count = None
            try:
                whole = getattr(prm.rdata, "wholeMsg", None) or ""
                count = parse_mwi_count(whole)
            except Exception as e:
                logging.debug("onMwiInfo(%s): %s", self.data.get("user"), e)
            self.app._ui(self.app._on_mwi_info, self, count)

        def onIncomingCall(self, prm):
            try:
                call = MyCall(self, self.app, prm.callId)
                server = self.data.get("server", "")
                unconditional = build_sip_target(self.data.get("forward_unconditional"), server)
                if unconditional:
                    logging.info("Encaminhamento incondicional para %s", unconditional)
                    self.app._redirect_incoming_call(call, unconditional, "incondicional")
                    return

                if self.app.call_state in ("IN_CALL", "HOLD"):
                    busy = build_sip_target(self.data.get("forward_busy"), server)
                    if busy:
                        logging.info("Encaminhamento por ocupado para %s", busy)
                        self.app._redirect_incoming_call(call, busy, "ocupado")
                        return

                try:
                    remote = call.getInfo().remoteUri
                except Exception:
                    remote = prm.rdata.wholeMsg[:80]
                logging.info("Chamada recebida de %s", remote)
                self.app._ui(self.app.on_incoming, call)

                no_answer = build_sip_target(self.data.get("forward_no_answer"), server)
                if no_answer:
                    try:
                        timeout = int(self.data.get("forward_no_answer_timeout", 20))
                    except (TypeError, ValueError):
                        timeout = 20
                    self.app._ui(
                        self.app._schedule_forward_no_answer,
                        call,
                        no_answer,
                        max(5, min(60, timeout)),
                    )
            except Exception as e:
                logging.error("Erro ao tratar chamada recebida: %s", e)

    class MyBuddy(pj.Buddy):
        """Assinatura SIP de presença de um URI monitorado."""

        def __init__(self, app, account, uri):
            super().__init__()
            self.app = app
            self.account = account
            self.uri = uri.lower()
            cfg = pj.BuddyConfig()
            cfg.uri = uri
            cfg.subscribe = True
            self.create(account, cfg)

        def onBuddyState(self):
            try:
                info = self.getInfo()
                pres = info.presStatus
                status = getattr(pres, "status", pj.PJSUA_BUDDY_STATUS_UNKNOWN)
                text = getattr(pres, "statusText", "") or ""
                activity = getattr(pres, "activity", pj.PJRPID_ACTIVITY_UNKNOWN)
                self.app._presence[self.uri] = {
                    "status": status,
                    "text": text,
                    "activity": activity,
                }
                self.app._ui(self.app._update_presence_ui)
            except Exception as e:
                logging.warning("Falha ao atualizar presença de %s: %s", self.uri, e)

    class MyCall(pj.Call):
        def __init__(self, acc, app, call_id=pj.PJSUA_INVALID_ID):
            super().__init__(acc, call_id)
            self.acc = acc
            self.app = app
            self.secure_media = False

        def onCallSdpCreated(self, prm):
            """Detecta SRTP no SDP negociado.

            Perfis RTP/SAVP (SDES) e UDP/TLS/RTP/SAVP (DTLS-SRTP) indicam
            que a mídia desta chamada está criptografada.
            """
            try:
                blob = ""
                try:
                    blob += prm.sdp.wholeSdp or ""
                except Exception:
                    pass
                try:
                    blob += "\n" + (prm.remSdp or "")
                except Exception:
                    pass
                self.secure_media = "SAVP" in blob
            except Exception as e:
                logging.debug("onCallSdpCreated: %s", e)
            self.app._ui(self.app._update_zrtp_ui, self)

        def onCallState(self, prm):
            self.app._ui(self.app.handle_call_state, self, prm)

        def onCallMediaState(self, prm):
            self.app._ui(self.app.on_call_media_state, self)

else:

    # Sem pjsua2 (Win/Mac): placeholders None. Qualquer uso deve ser cercado
    # por `if self._sip_available` em app.py.
    MyAccount = None
    MyBuddy = None
    MyCall = None
