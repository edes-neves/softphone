"""Testes de regressão para bugs pontuais do app (camada pura, sem Qt).
"""
import types

import pytest

try:
    from voice_neves import app as app_module
except Exception as e:  # PySide6/Qt indisponivel (ex.: CI sem display/libEGL)
    pytest.skip(f"app (PySide6/Qt) indisponivel neste ambiente: {e}", allow_module_level=True)


def test_dialable_from_uri_prefixes():
    # BUG 06: sips:/tel: não eram normalizados (só sip:)
    m = app_module.SoftphoneApp._dialable_from_uri
    assert m(None, "sips:3000@pbx;transport=tls") == "3000"
    assert m(None, '"Ana" <sips:3000@pbx>') == "3000"
    assert m(None, "tel:+5511987654321") == "+5511987654321"
    assert m(None, "tel:3000;phone-context=default@pbx") == "3000"
    # comportamento de sip: preservado
    assert m(None, "sip:4000@pbx") == "4000"
    assert m(None, '"Ana" <sip:4000@pbx>') == "4000"
    assert m(None, "3000") == "3000"
    assert m(None, "") == ""


def _audio_call(pkt, loss):
    rtcp = types.SimpleNamespace(
        rttUsec=1000,
        rxStat=types.SimpleNamespace(jitterUsec=500, pkt=pkt, loss=loss),
    )
    media = [types.SimpleNamespace(
        type=app_module.pj.PJMEDIA_TYPE_AUDIO,
        status=app_module.pj.PJSUA_CALL_MEDIA_ACTIVE,
        index=0,
    )]
    call = types.SimpleNamespace(
        getInfo=lambda: types.SimpleNamespace(media=media),
    )
    call.getStreamStat = lambda mi: types.SimpleNamespace(rtcp=rtcp)
    return call


def _qos_app(call):
    app = types.SimpleNamespace(current_call=call, call_state="IN_CALL")
    # _read_qos delega para o helper estático _qos_number via self
    app._qos_number = app_module.SoftphoneApp._qos_number
    return app


def test_read_qos_ignores_too_few_packets():
    # BUG 07: pkt == 0 (início de chamada) reportava "perda 100%" falsa
    app = _qos_app(_audio_call(pkt=0, loss=0))
    assert app_module.SoftphoneApp._read_qos(app) is None
    # sem chamada ativa também retorna None
    app.current_call = None
    assert app_module.SoftphoneApp._read_qos(app) is None
    # amostra suficiente passa a reportar os valores
    app.current_call = _audio_call(pkt=100, loss=5)
    rtt, jitter, loss_pct = app_module.SoftphoneApp._read_qos(app)
    assert loss_pct == 4.8  # 5 / (100+5)
    assert rtt == 1.0
    assert jitter == 0.5


def test_update_result_with_none_info():
    # BUG 10: info None quebrava em info.get("version") -> AttributeError
    calls = []
    app = types.SimpleNamespace()
    app._error = lambda *a: calls.append(a)
    app._info = lambda *a: calls.append(a)
    app._ask_yes = lambda *a: False
    app_module.SoftphoneApp._on_menu_update_result(app, None, "1.0.0", None)
    assert calls
    assert calls[0][0] == "Verificar atualização"
    # fluxo de erro não muda
    calls.clear()
    app_module.SoftphoneApp._on_menu_update_result(app, None, "1.0.0", "rede fora")
    assert calls and "Verifique sua conexão" in calls[0][1]


def test_failover_backoff(monkeypatch):
    # BUG 18: cooldown dobra a cada falha consecutiva, com teto em 600s
    seen = {}

    def fake_failover_target(current, primary, backup, last_attempt, cooldown_sec, now):
        seen["cooldown"] = cooldown_sec
        return "pbx.b"

    monkeypatch.setattr(app_module, "failover_target", fake_failover_target)
    app = types.SimpleNamespace(
        FAILOVER_COOLDOWN=30,
        FAILOVER_MAX_COOLDOWN=600,
    )
    app._recreate_account = lambda entry, target: None
    app.show_toast = lambda msg: None
    m = app_module.SoftphoneApp._maybe_failover

    entry = {
        "data": {"server": "pbx.a", "backup_server": "pbx.b"},
        "server_used": "pbx.a",
        "_failover_at": 0.0,
        "_failover_attempts": 0,
    }
    m(app, entry)
    assert seen["cooldown"] == 30
    assert entry["_failover_attempts"] == 1
    m(app, entry)
    assert seen["cooldown"] == 60
    m(app, entry)
    assert seen["cooldown"] == 120
    entry["_failover_attempts"] = 20
    m(app, entry)
    assert seen["cooldown"] == 600  # teto do backoff
    assert entry["_failover_attempts"] == 21


def test_volume_curve_perceptual():
    # ITEM 6: curva perceptual — 0 -> mudo, 5 -> ~0.66 (não 1.0), 10 -> 2.0
    c = app_module._volume_curve
    assert c(0) == 0.0
    assert c(10) == 2.0
    mid = c(5)
    assert 0.6 <= mid <= 0.7, mid
    # climps e valores inválidos nunca estouram domínio
    assert c(55) == 2.0
    assert c(-3) == 0.0
    assert c("abc") == c(5)  # entrada inválida usa o ponto médio
    assert c(None) == c(5)


def test_audio_error_hint_mentions_bridge():
    # ITEM 7: a dica de áudio agora cobre PipeWire/PulseAudio e aplay -L
    hint = app_module.audio_error_hint()
    assert "PipeWire" in hint
    assert "aplay -L" in hint
    assert "pactl info" in hint


def _audio_app(endpoint, call_state="IDLE", has_audio=True):
    app = types.SimpleNamespace(
        endpoint=endpoint,
        _has_audio=has_audio,
        call_state=call_state,
        _cached_ins=[],
        _cached_outs=[],
    )
    return app


def test_validate_audio_devices_missing_device_falls_back():
    # ITEM 3: device ativo sumiu da enumeração -> volta ao padrão do sistema
    devs = [
        types.SimpleNamespace(name="hw:0", inputCount=2, outputCount=2),
        types.SimpleNamespace(name="pipewire", inputCount=2, outputCount=2),
    ]
    adm = types.SimpleNamespace(
        enumDev2=lambda: [d for d in devs],
        getCaptureDev=lambda: 7,
        getPlaybackDev=lambda: 7,
    )
    ep = types.SimpleNamespace(audDevManager=lambda: adm)
    app = _audio_app(ep)
    opened = []
    app._try_open_sound = lambda c, p: opened.append((c, p)) or None
    app_module.SoftphoneApp._validate_audio_devices(app)
    assert opened == [(-1, -2)]
    # caches atualizados (hotplug refletido)
    assert len(app._cached_ins) == 2
    assert len(app._cached_outs) == 2


def test_validate_audio_devices_keeps_present_device():
    devs = [types.SimpleNamespace(name="hw:0", inputCount=2, outputCount=2)]
    adm = types.SimpleNamespace(
        enumDev2=lambda: list(devs),
        getCaptureDev=lambda: 0,
        getPlaybackDev=lambda: 0,
    )
    ep = types.SimpleNamespace(audDevManager=lambda: adm)
    app = _audio_app(ep)
    opened = []
    app._try_open_sound = lambda c, p: opened.append((c, p)) or None
    app_module.SoftphoneApp._validate_audio_devices(app)
    assert opened == []  # nada a fazer quando o device segue presente


def test_validate_audio_devices_skips_active_call():
    adm = types.SimpleNamespace(
        enumDev2=lambda: [types.SimpleNamespace(name="a", inputCount=1, outputCount=1)],
        getCaptureDev=lambda: 9,
        getPlaybackDev=lambda: 9,
    )
    ep = types.SimpleNamespace(audDevManager=lambda: adm)
    app = _audio_app(ep, call_state="IN_CALL")
    opened = []
    app._try_open_sound = lambda c, p: opened.append((c, p)) or None
    app_module.SoftphoneApp._validate_audio_devices(app)
    assert opened == []  # nunca troca de device no meio de chamada


def test_validate_audio_devices_never_raises():
    # endpoint None / sem áudio / enumeração falha: sempre retorna quieto
    app = _audio_app(None)
    app_module.SoftphoneApp._validate_audio_devices(app)
    app = _audio_app(None, has_audio=False)
    app_module.SoftphoneApp._validate_audio_devices(app)

    class BoomError(Exception):
        pass

    def boom():
        raise BoomError("snd_dev nenhum")

    adm = types.SimpleNamespace(enumDev2=boom, getCaptureDev=boom, getPlaybackDev=boom)
    ep = types.SimpleNamespace(audDevManager=lambda: adm)
    app = _audio_app(ep)
    app_module.SoftphoneApp._validate_audio_devices(app)


def test_apply_media_config_account_level():
    # ITEM 2: AGC/VAD por conta, seguindo audio.* da config
    class FakeMedia:
        enableCaptureAgc = False
        enablePlaybackAgc = False
        noVad = False

    media = FakeMedia()
    acfg = types.SimpleNamespace(mediaConfig=media)
    app = types.SimpleNamespace(config_data={"audio": {
        "agc_capture": True, "agc_playback": True, "vad": False,
    }})
    app_module.SoftphoneApp._apply_media_config(app, acfg)
    assert media.enableCaptureAgc is True
    assert media.enablePlaybackAgc is True
    assert media.noVad is True  # vad=False -> noVad=True


def test_apply_media_config_degrades_without_fields():
    # builds sem enableCaptureAgc/noVad: nada é setado e nada quebra
    class FakeMedia:
        pass

    acfg = types.SimpleNamespace(mediaConfig=FakeMedia())
    app = types.SimpleNamespace(config_data={"audio": {
        "agc_capture": True, "agc_playback": True, "vad": True,
    }})
    app_module.SoftphoneApp._apply_media_config(app, acfg)
    assert not hasattr(acfg.mediaConfig, "noVad")
    # sem seção "audio" na config -> defaults (provável build real)
    app = types.SimpleNamespace(config_data={})
    media = FakeMedia()
    app_module.SoftphoneApp._apply_media_config(app, types.SimpleNamespace(mediaConfig=media))


def test_recreate_account_drops_buddy_refs():
    # pjsua2 (SWIG) não expõe Buddy.delete(): o antigo buddy.delete() falhava
    # silenciosamente e a assinatura nunca era removida de verdade. A remoção
    # real ocorre no destrutor C++ (~Buddy -> pjsua_buddy_del); garantimos que
    # _recreate_account solta as referências explicitamente de forma
    # determinística (refcount do CPython), sem depender do coletor de ciclos.
    destroyed = []

    class FakeBuddy:
        def __init__(self, name):
            self.name = name

        def __del__(self):
            destroyed.append(self.name)

    class FakeAcc:
        def __init__(self):
            self.shutdown_called = False

        def shutdown(self):
            self.shutdown_called = True

    app = types.SimpleNamespace()
    entry = {
        "data": {"user": "1001", "server": "pbx.a", "backup_server": "pbx.b"},
        "server_used": "pbx.a",
        "acc": FakeAcc(),
        "buddies": [FakeBuddy("A"), FakeBuddy("B")],
        "_failover_at": 0.0,
        "_failover_attempts": 2,
    }
    app.accounts = [entry]
    app.register_account = lambda data, current_server=None: {
        "data": dict(data), "server_used": current_server,
        "buddies": [], "_failover_at": 0.0, "_failover_attempts": 0,
    }
    app.refresh = lambda: None
    app.update_presence = lambda: None
    app.show_toast = lambda msg: None
    app._drop_presence_buddies = types.MethodType(
        app_module.SoftphoneApp._drop_presence_buddies, app
    )
    # _build_account_config é chamado antes do modify; o FakeAcc não expõe
    # modify(), então o _recreate_account cai no caminho de recriação (o que
    # este teste verifica: soltar as referências dos buddies).
    app._build_account_config = lambda data, current_server=None: (object(), current_server)
    app_module.SoftphoneApp._recreate_account(app, entry, "pbx.b")

    assert entry["acc"].shutdown_called  # shutdown da conta ainda ocorre
    assert sorted(destroyed) == ["A", "B"]  # wrappers destruídos por refcount
    assert entry["buddies"] == []  # sem referências penduradas


def test_close_event_hides_to_tray_when_active():
    # O X com bandeja ativa deve ignorar o fechamento e esconder a janela.
    got = {}

    class _FakeTray:
        pass

    self_ = types.SimpleNamespace(
        _tray_icon=_FakeTray(),
        _quitting=False,
        hide=lambda: got.__setitem__("hide", True),
        show_toast=lambda *a, **k: got.__setitem__("toast", True),
        close=lambda: got.__setitem__("close", True),
    )
    event = types.SimpleNamespace(
        ignore=lambda: got.__setitem__("ignore", True),
        accept=lambda: got.__setitem__("accept", True),
    )
    app_module.SoftphoneApp.closeEvent(self_, event)
    assert got.get("ignore") is True
    assert got.get("hide") is True
    assert got.get("close") is None


def test_close_event_minimizes_when_no_tray():
    # Sem bandeja, o X deve MINIMIZAR (fallback), não encerrar o app.
    got = {}
    self_ = types.SimpleNamespace(
        _tray_icon=None,
        _quitting=False,
        hide=lambda: got.__setitem__("hide", True),
        showMinimized=lambda: got.__setitem__("minimize", True),
        show_toast=lambda *a, **k: got.__setitem__("toast", True),
        close=lambda: got.__setitem__("close", True),
    )
    event = types.SimpleNamespace(
        ignore=lambda: got.__setitem__("ignore", True),
        accept=lambda: got.__setitem__("accept", True),
    )
    app_module.SoftphoneApp.closeEvent(self_, event)
    assert got.get("ignore") is True
    assert got.get("minimize") is True
    assert got.get("hide") is None
    assert got.get("close") is None


def test_close_event_quits_when_quitting_flag():
    # Encerramento explícito (menu Sair) aceita o evento e não minimiza.
    got = {}
    self_ = types.SimpleNamespace(
        _tray_icon=object(),
        _quitting=True,
        hide=lambda: got.__setitem__("hide", True),
        showMinimized=lambda: got.__setitem__("minimize", True),
    )
    event = types.SimpleNamespace(
        ignore=lambda: got.__setitem__("ignore", True),
        accept=lambda: got.__setitem__("accept", True),
    )
    app_module.SoftphoneApp.closeEvent(self_, event)
    assert got.get("accept") is True
    assert got.get("ignore") is None
    assert got.get("hide") is None
    assert got.get("minimize") is None


def test_quit_app_closes_window_and_stops_loop(monkeypatch):
    # BUG: a action "Sair" da bandeja estava ligada a self.close; quando isso
    # resolvia para o slot C++ QWidget.close(), só emitia closeEvent -- que
    # ignoramos enquanto o app deve continuar vivo -- e nada acontecia.
    # _quit_app marca _quitting, faz o teardown (close custom), fecha a janela
    # de verdade (QMainWindow.close) e para o loop de eventos.
    got = {}
    closed = {}

    self_ = types.SimpleNamespace(
        _quitting=False,
        close=lambda: got.__setitem__("custom_close", True),
        qapp=types.SimpleNamespace(quit=lambda: got.__setitem__("quit", True)),
    )
    monkeypatch.setattr(
        app_module.QMainWindow,
        "close",
        lambda obj: closed.__setitem__("qt_close", True),
    )
    app_module.SoftphoneApp._quit_app(self_)
    assert self_._quitting is True
    assert got.get("custom_close") is True   # teardown executado
    assert closed.get("qt_close") is True    # janela fechada de verdade
    assert got.get("quit") is True           # loop de eventos encerrado


def test_setup_tray_disabled_without_notification_area(monkeypatch):
    # Sem área de notificação (offscreen/headless), a bandeja fica desativada
    # e o app volta ao comportamento de fechar no X (sem crash).
    self_ = types.SimpleNamespace(_tray_icon=object(), _tray_menu=object())
    monkeypatch.setattr(
        app_module.QSystemTrayIcon,
        "isSystemTrayAvailable",
        staticmethod(lambda: False),
    )
    app_module.SoftphoneApp._setup_tray(self_)
    assert self_._tray_icon is None
    assert self_._tray_menu is None


def test_auto_register_accounts_skips_disabled(monkeypatch):
    # contas com enabled=False não devem ser registradas.
    registered = []
    self_ = types.SimpleNamespace(
        _sip_available=True,
        accounts=[],
        config_data={"accounts": [
            {"user": "100", "server": "pbx", "enabled": True},
            {"user": "200", "server": "pbx", "enabled": False},
            {"user": "300", "server": "pbx"},  # ausente -> habilitada
        ]},
        refresh=lambda: None,
        update_presence=lambda: None,
        _publish_presence=lambda: None,
        register_account=lambda data: registered.append(data["user"]),
    )
    app_module.SoftphoneApp.auto_register_accounts(self_)
    assert registered == ["100", "300"]


def test_toggle_account_enabled(monkeypatch):
    # botão direito: alterna o flag persistindo em config e re-registra.
    saved = []
    toasts = []
    recheck = []
    cfg = {"accounts": [{"user": "100", "server": "pbx", "enabled": True}]}
    self_ = types.SimpleNamespace(
        call_state="IDLE",
        config_data=cfg,
        show_toast=lambda msg: toasts.append(msg),
        auto_register_accounts=lambda: recheck.append(True),
        _warn=lambda *a: None,
        _error=lambda *a: None,
    )
    self_._config_account_by_key = types.MethodType(
        app_module.SoftphoneApp._config_account_by_key, self_
    )
    monkeypatch.setattr(app_module, "save_config", lambda data: saved.append(data))

    m = app_module.SoftphoneApp._toggle_account_enabled
    m(self_, "100@pbx")
    assert cfg["accounts"][0]["enabled"] is False
    assert saved and recheck == [True]
    assert "desabilitada" in toasts[-1]

    m(self_, "100@pbx")
    assert cfg["accounts"][0]["enabled"] is True
    assert "habilitada" in toasts[-1]


def test_toggle_account_enabled_blocked_during_call(monkeypatch):
    # durante chamada não altera nada (nem salva).
    saved = []
    warned = []
    cfg = {"accounts": [{"user": "100", "server": "pbx", "enabled": True}]}
    self_ = types.SimpleNamespace(
        call_state="IN_CALL",
        config_data=cfg,
        _warn=lambda *a: warned.append(a),
        show_toast=lambda *a: None,
        auto_register_accounts=lambda: None,
    )
    self_._config_account_by_key = types.MethodType(
        app_module.SoftphoneApp._config_account_by_key, self_
    )
    monkeypatch.setattr(app_module, "save_config", lambda data: saved.append(data))
    app_module.SoftphoneApp._toggle_account_enabled(self_, "100@pbx")
    assert cfg["accounts"][0]["enabled"] is True
    assert warned and not saved


def test_toggle_account_enabled_missing_account(monkeypatch):
    # chave inexistente -> erro, sem salvar.
    saved = []
    errors = []
    self_ = types.SimpleNamespace(
        call_state="IDLE",
        config_data={"accounts": []},
        _error=lambda *a: errors.append(a),
        show_toast=lambda *a: None,
        auto_register_accounts=lambda: None,
    )
    self_._config_account_by_key = types.MethodType(
        app_module.SoftphoneApp._config_account_by_key, self_
    )
    monkeypatch.setattr(app_module, "save_config", lambda data: saved.append(data))
    app_module.SoftphoneApp._toggle_account_enabled(self_, "999@pbx")
    assert errors and not saved


class _FakeAcc:
    def __init__(self):
        self.modified = None
        self.shutdown_called = False
        self.registration_renew = None

    def modify(self, cfg):
        self.modified = cfg

    def setRegistration(self, renew):
        self.registration_renew = renew

    def shutdown(self):
        self.shutdown_called = True


class _FakeAccountConfig:
    def __init__(self):
        self.idUri = ""
        self.regConfig = types.SimpleNamespace(registrarUri="")
        self.mwiConfig = types.SimpleNamespace(enabled=False)
        self.sipConfig = types.SimpleNamespace(authCreds=[])


def _rereg_app(entry):
    app = types.SimpleNamespace(accounts=[entry], _drop_presence_buddies=lambda e: None)
    app._build_account_config = types.MethodType(
        app_module.SoftphoneApp._build_account_config, app
    )
    app._apply_security_config = lambda cfg: None
    app._apply_nat_config = lambda cfg: None
    app._apply_video_config = lambda cfg: None
    app._apply_media_config = lambda cfg: None
    app.register_account = lambda data, current_server=None: entry
    return app


def test_reregister_same_identity_uses_modify(monkeypatch):
    # mesma identidade -> modify() na conta viva (sem shutdown), re-registra
    # na hora e evita o "Object is busy" do shutdown+create imediato.
    acc = _FakeAcc()
    entry = {"acc": acc, "data": {"user": "100", "server": "pbx"},
             "server_used": "pbx", "status": "ONLINE",
             "_failover_at": 1.0, "_failover_attempts": 3}
    monkeypatch.setattr(app_module.pj, "AccountConfig", _FakeAccountConfig, raising=False)
    monkeypatch.setattr(app_module.pj, "AuthCredInfo",
                        lambda *a, **k: object(), raising=False)
    monkeypatch.setattr(app_module, "secrets", types.SimpleNamespace(get=lambda k, d="": ""))
    app = _rereg_app(entry)
    new_data = {"user": "100", "server": "pbx", "password": "nova"}
    out = app_module.SoftphoneApp._reregister_account(app, entry, new_data)
    assert out is entry
    assert acc.modified is not None            # modify aplicado (já re-registra)
    assert acc.shutdown_called is False        # NÃO recriou
    assert entry["data"] == new_data
    assert entry["status"] == "REGISTERING"
    assert entry["_failover_attempts"] == 0


def test_reregister_changed_identity_recreates(monkeypatch):
    # identidade mudou -> shutdown da antiga, remove da lista e recria.
    acc = _FakeAcc()
    entry = {"acc": acc, "data": {"user": "100", "server": "pbx"},
             "server_used": "pbx", "status": "ONLINE"}
    created = []
    monkeypatch.setattr(app_module, "secrets", types.SimpleNamespace(get=lambda k, d="": ""))
    app = _rereg_app(entry)
    app.register_account = lambda data, current_server=None: created.append(data)
    new_data = {"user": "200", "server": "pbx"}
    app_module.SoftphoneApp._reregister_account(app, entry, new_data)
    assert acc.shutdown_called is True
    assert entry not in app.accounts            # antiga removida
    assert created == [new_data]                # nova criada


def test_failover_after_sec_defaults_and_clamps():
    m = app_module.SoftphoneApp._failover_after_sec
    assert m(types.SimpleNamespace(config_data={})) == 20
    assert m(types.SimpleNamespace(config_data={"registration": {}})) == 20
    assert m(types.SimpleNamespace(
        config_data={"registration": {"failover_after_sec": 7}})) == 7
    assert m(types.SimpleNamespace(
        config_data={"registration": {"failover_after_sec": 0}})) == 3
    assert m(types.SimpleNamespace(
        config_data={"registration": {"failover_after_sec": 9999}})) == 300
    assert m(types.SimpleNamespace(
        config_data={"registration": {"failover_after_sec": "abc"}})) == 20


def test_check_failover_fires_after_threshold(monkeypatch):
    # conta presa em REGISTERING sem ONLINE além do tempo -> dispara failover.
    import time as _time
    now = 1000.0
    entry = {
        "acc": object(),
        "data": {"user": "100", "server": "pbx", "backup_server": "pbx2"},
        "server_used": "pbx", "status": "REGISTERING",
        "enabled": True, "_reg_started_at": now - 25,  # 25s > 20
    }
    app = types.SimpleNamespace(
        accounts=[entry], _sip_available=True, call_state="IDLE",
        config_data={"registration": {"failover_after_sec": 20}},
    )
    app._failover_after_sec = types.MethodType(
        app_module.SoftphoneApp._failover_after_sec, app
    )
    fired = []
    app._maybe_failover = lambda e: fired.append(e)
    monkeypatch.setattr(_time, "time", lambda: now)
    app_module.SoftphoneApp._check_failover(app)
    assert fired == [entry]


def test_check_failover_skips_no_backup_online_and_threshold(monkeypatch):
    import time as _time
    now = 1000.0
    base = {"acc": object(), "server_used": "pbx", "status": "REGISTERING",
            "enabled": True, "_reg_started_at": now - 25}
    no_backup = dict(base, data={"user": "100", "server": "pbx"})
    online = dict(base, data={"user": "100", "server": "pbx", "backup_server": "pbx2"})
    online["status"] = "ONLINE"
    fresh = dict(base, data={"user": "100", "server": "pbx", "backup_server": "pbx2"})
    fresh["_reg_started_at"] = now - 5  # < 20
    disabled = dict(fresh, data={"user": "100", "server": "pbx", "backup_server": "pbx2"})
    disabled["enabled"] = False
    disabled["_reg_started_at"] = now - 25
    app = types.SimpleNamespace(
        accounts=[no_backup, online, fresh, disabled],
        _sip_available=True, call_state="IDLE",
        config_data={"registration": {"failover_after_sec": 20}},
    )
    app._failover_after_sec = types.MethodType(
        app_module.SoftphoneApp._failover_after_sec, app
    )
    fired = []
    app._maybe_failover = lambda e: fired.append(e)
    monkeypatch.setattr(_time, "time", lambda: now)
    app_module.SoftphoneApp._check_failover(app)
    assert fired == []


def test_check_failover_skips_during_call(monkeypatch):
    import time as _time
    now = 1000.0
    entry = {"acc": object(),
             "data": {"user": "100", "server": "pbx", "backup_server": "pbx2"},
             "server_used": "pbx", "status": "REGISTERING",
             "enabled": True, "_reg_started_at": now - 99}
    app = types.SimpleNamespace(
        accounts=[entry], _sip_available=True, call_state="IN_CALL",
        config_data={"registration": {"failover_after_sec": 20}},
    )
    app._failover_after_sec = types.MethodType(
        app_module.SoftphoneApp._failover_after_sec, app
    )
    fired = []
    app._maybe_failover = lambda e: fired.append(e)
    monkeypatch.setattr(_time, "time", lambda: now)
    app_module.SoftphoneApp._check_failover(app)
    assert fired == []


def test_recreate_account_uses_modify(monkeypatch):
    # Failover na conta viva: modify() troca o servidor SEM shutdown (evita
    # o "Object is busy" do shutdown+create imediato).
    acc = _FakeAcc()
    entry = {"acc": acc, "data": {"user": "100", "server": "pbx",
                                  "backup_server": "pbx2"},
             "server_used": "pbx", "status": "OFFLINE"}
    monkeypatch.setattr(app_module.pj, "AccountConfig", _FakeAccountConfig, raising=False)
    monkeypatch.setattr(app_module.pj, "AuthCredInfo",
                        lambda *a, **k: object(), raising=False)
    monkeypatch.setattr(app_module, "secrets", types.SimpleNamespace(get=lambda k, d="": ""))
    app = types.SimpleNamespace(
        accounts=[entry], _drop_presence_buddies=lambda e: None,
        refresh=lambda: None, update_presence=lambda: None,
        register_account=lambda data, current_server=None: entry,
    )
    app._build_account_config = types.MethodType(
        app_module.SoftphoneApp._build_account_config, app
    )
    app._apply_security_config = lambda cfg: None
    app._apply_nat_config = lambda cfg: None
    app._apply_video_config = lambda cfg: None
    app._apply_media_config = lambda cfg: None
    app._failover_after_sec = types.MethodType(
        app_module.SoftphoneApp._failover_after_sec, app
    )
    app.config_data = {}
    old = app.register_account
    called = {"recreate": False}

    def _reg(data, current_server=None):
        called["recreate"] = True
        return old(data, current_server)

    app.register_account = _reg
    out = app_module.SoftphoneApp._recreate_account(app, entry, "pbx2")
    assert out is entry
    assert acc.modified is not None            # modify aplicado
    assert acc.shutdown_called is False        # NÃO recriou
    assert entry["server_used"] == "pbx2"      # aponta para o backup
    assert entry["status"] == "REGISTERING"
    assert called["recreate"] is False
