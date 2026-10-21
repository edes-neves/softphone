"""Teste de integração: reconexão de conta ao editar, sem reiniciar o app.

Sobe um mini-servidor SIP UDP local (responde 200 OK a REGISTER) e exercita
o MÉTODO REAL do app (`SoftphoneApp._reregister_account`) para provar que a
conta volta a ficar ONLINE após a edição, sem restart e sem o
"Object is busy (PJSIP_EBUSY)" do shutdown+create imediato.

É **pulado por padrão** (mantém o `pytest tests/` offline e rápido). Rode
explicitamente com:

    SIP_INTEGRATION_TEST=1 python -m pytest tests/test_account_reregister_integration.py -v
"""
import os
import socket
import threading
import time
import types

import pytest

try:
    import pjsua2 as pj
except Exception as e:  # pragma: no cover - ambiente sem binding pjsua2
    pj = None
    _PJ_ERR = e
else:
    _PJ_ERR = None

try:
    from voice_neves import app as app_module
except Exception as e:  # PySide6/Qt indisponível (ex.: CI sem display)
    app_module = None
    _APP_ERR = e
else:
    _APP_ERR = None


pytestmark = pytest.mark.skipif(
    os.environ.get("SIP_INTEGRATION_TEST") != "1",
    reason="teste de integração SIP: defina SIP_INTEGRATION_TEST=1 para rodar",
)


def _skip_if_unavailable():
    if pj is None:
        pytest.skip(f"pjsua2 indisponível: {_PJ_ERR}")
    if app_module is None:
        pytest.skip(f"app (PySide6/Qt) indisponível: {_APP_ERR}")


def _free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _MiniSipServer:
    """Servidor SIP UDP mínimo: responde 200 OK a qualquer REGISTER."""

    def __init__(self):
        self.port = _free_udp_port()
        self.count = 0
        self._running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", self.port))
        self._sock.settimeout(0.2)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while self._running:
            try:
                data, addr = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            text = data.decode(errors="ignore")
            if not text.startswith("REGISTER"):
                continue
            self.count += 1
            h = {}
            for line in text.split("\r\n"):
                if ":" in line:
                    k, _, v = line.partition(":")
                    h[k.strip().lower()] = v.strip()
            resp = (
                "SIP/2.0 200 OK\r\n"
                f"Via: {h.get('via', '')}\r\n"
                f"From: {h.get('from', '')}\r\n"
                f"To: {h.get('to', '')};tag=srv\r\n"
                f"Call-ID: {h.get('call-id', '')}\r\n"
                f"CSeq: {h.get('cseq', '')}\r\n"
                f"Contact: <sip:127.0.0.1:{self.port}>\r\n"
                "Expires: 300\r\n"
                "Content-Length: 0\r\n\r\n"
            )
            self._sock.sendto(resp.encode(), addr)

    def stop(self):
        self._running = False
        try:
            self._thread.join(timeout=2)
        finally:
            self._sock.close()


@pytest.fixture(scope="module")
def sip_env():
    """Endpoint pjsua2 + mini-servidor SIP; devolve (endpoint, server).

    O pjsua2 só permite UM Endpoint por processo: recriar após `libDestroy`
    aborta. Por isso o escopo é de módulo e o servidor reinicia por teste.
    """
    _skip_if_unavailable()
    ep = pj.Endpoint()
    ep.libCreate()
    try:
        cfg = pj.EpConfig()
        cfg.logConfig.level = 0
        ep.libInit(cfg)
        tc = pj.TransportConfig()
        tc.port = 0
        ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tc)
        ep.libStart()
        yield ep
    finally:
        try:
            ep.libDestroy()
        except Exception:
            pass


@pytest.fixture
def sip_server():
    server = _MiniSipServer()
    try:
        yield server
    finally:
        server.stop()


def _app_stub(ep):
    """SoftphoneApp mínimo usando os métodos REAIS de gerência de conta."""
    import queue

    a = app_module.SoftphoneApp.__new__(app_module.SoftphoneApp)
    a.endpoint = ep
    a.accounts = []
    a._main_tid = threading.get_ident()
    a._ui_queue = queue.Queue()
    a.config_data = {"accounts": [], "security": {}, "nat": {}, "video": {}, "audio": {}}
    a._apply_security_config = lambda c: None
    a._apply_nat_config = lambda c: None
    a._apply_video_config = lambda c: None
    a._apply_media_config = lambda c: None
    a._create_presence_buddies = lambda e: None
    a._drop_presence_buddies = lambda e: None
    a._on_account_reg_failed = lambda acc: None
    a.refresh = lambda: None
    a.update_presence = lambda: None
    a.show_toast = lambda *args, **kw: None
    # usa o update_account_status REAL (é ele que marca a conta ONLINE/OFFLINE)
    a.update_account_status = types.MethodType(
        app_module.SoftphoneApp.update_account_status, a
    )
    # os callbacks pjsua2 chegam na thread do pump == _main_tid, então _ui()
    # executa direto e _ui_queue não é tocado.
    return a


def _pump(ep, seconds, app=None):
    end = time.time() + seconds
    while time.time() < end:
        ep.libHandleEvents(50)
        if app is not None:
            _drain_ui(app)


def _drain_ui(app):
    while True:
        try:
            fn, args = app._ui_queue.get_nowait()
        except Exception:
            break
        fn(*args)


def test_edit_account_reconnects_without_restart(sip_env, sip_server, monkeypatch):
    ep = sip_env
    server = sip_server
    a = _app_stub(ep)

    store = {}
    monkeypatch.setattr(
        app_module,
        "secrets",
        types.SimpleNamespace(
            get=lambda k, d="": store.get(k, d),
            set=lambda k, v: store.__setitem__(k, v),
            delete=lambda k: store.pop(k, None),
        ),
        raising=False,
    )

    user_server = f"127.0.0.1:{server.port}"
    store[f"100@{user_server}"] = "p1"
    entry = a.register_account({"user": "100", "server": user_server})
    _pump(ep, 2, a)
    assert entry["status"] == "ONLINE"
    regs_after_create = server.count
    assert regs_after_create >= 1

    # Edita a conta (muda a senha) -> deve reconectar na hora, sem restart.
    store[f"100@{user_server}"] = "p2-nova"
    a._reregister_account(entry, {"user": "100", "server": user_server})
    _pump(ep, 2, a)

    assert entry is a.accounts[0]            # mesma conta, não recriada
    assert server.count > regs_after_create  # REGISTER reenviado
    assert entry["status"] == "ONLINE"       # reconectou sem reiniciar


def test_edit_account_changed_identity_recreates(sip_env, sip_server, monkeypatch):
    ep = sip_env
    server = sip_server
    a = _app_stub(ep)
    store = {}
    monkeypatch.setattr(
        app_module,
        "secrets",
        types.SimpleNamespace(
            get=lambda k, d="": store.get(k, d),
            set=lambda k, v: store.__setitem__(k, v),
            delete=lambda k: store.pop(k, None),
        ),
        raising=False,
    )

    user_server = f"127.0.0.1:{server.port}"
    store[f"100@{user_server}"] = "p1"
    entry = a.register_account({"user": "100", "server": user_server})
    _pump(ep, 2, a)
    old_acc = entry["acc"]

    # Muda o ramal -> identidade muda -> a conta antiga é destruída e a nova criada.
    store[f"200@{user_server}"] = "p1"
    a._reregister_account(entry, {"user": "200", "server": user_server})
    _pump(ep, 2, a)

    assert entry not in a.accounts
    assert len(a.accounts) == 1
    assert a.accounts[0]["acc"] is not old_acc
    assert a.accounts[0]["data"]["user"] == "200"


def _failover_app(ep, failover_after=3):
    """App stub com os métodos REAIS de failover (watchdog + troca de servidor)."""
    a = _app_stub(ep)
    a._sip_available = True
    a.call_state = "IDLE"
    a.config_data["registration"] = {"failover_after_sec": failover_after}
    for name in ("_failover_after_sec", "_check_failover", "_maybe_failover",
                 "_recreate_account", "_build_account_config"):
        setattr(a, name, types.MethodType(
            getattr(app_module.SoftphoneApp, name), a
        ))
    return a


def test_failover_switches_to_backup_without_restart(
        sip_env, sip_server, monkeypatch):
    ep = sip_env
    backup = sip_server
    a = _failover_app(ep, failover_after=3)
    store = {}
    monkeypatch.setattr(
        app_module, "secrets",
        types.SimpleNamespace(
            get=lambda k, d="": store.get(k, d),
            set=lambda k, v: store.__setitem__(k, v),
            delete=lambda k: store.pop(k, None),
        ),
        raising=False,
    )

    # primário morto (porta livre) + backup acessível (mini-servidor).
    dead_port = _free_udp_port()
    data = {
        "user": "100",
        "server": f"127.0.0.1:{dead_port}",
        "backup_server": f"127.0.0.1:{backup.port}",
    }
    store[f"100@127.0.0.1:{dead_port}"] = "p1"
    entry = a.register_account(data)

    # roda o watchdog até a conta mudar para o backup (config: 3 s).
    deadline = time.time() + 15
    switched = False
    while time.time() < deadline:
        _pump(ep, 0.4, a)
        a._check_failover()
        if entry.get("server_used") == f"127.0.0.1:{backup.port}":
            switched = True
            break

    assert switched, "failover não trocou para o backup a tempo"
    assert entry is a.accounts[0]                       # mesma conta (modify)
    _pump(ep, 2, a)
    assert backup.count >= 1                            # backup recebeu REGISTER
    assert entry["status"] == "ONLINE"                  # registrou no backup
