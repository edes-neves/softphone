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
    app_module.SoftphoneApp._recreate_account(app, entry, "pbx.b")

    assert entry["acc"].shutdown_called  # shutdown da conta ainda ocorre
    assert sorted(destroyed) == ["A", "B"]  # wrappers destruídos por refcount
    assert entry["buddies"] == []  # sem referências penduradas
