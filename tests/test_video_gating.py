"""Garante o gate de video automatico por enumeracao (sem reter a camera).

Contexto: este build do PJSIP NÃO libera o dispositivo V4L2 no
VideoPreview.stop() — a camera aberta fica presa pro resto do processo e
reabri-la (previa manual / video de chamada) da "ocupado". Logo, o probe
que abria a camera no startup impedia o botao "Ver previa" de funcionar.

Fix: o softphone NÃO abre a camera num probe de startup. Apenas enumera os
dispositivos de captura e escolhe a melhor (salva -> 0 -> primeira). A
camera e aberta sob demanda (previa manual / chamada), quando e a primeira
(e unica) abertura.
"""

import types

import pytest

try:
    from voice_neves import app as app_module
except Exception as e:  # PySide6/Qt indisponivel (ex.: CI sem display/libEGL)
    pytest.skip(f"app (PySide6/Qt) indisponivel neste ambiente: {e}", allow_module_level=True)

REAL_PJ = app_module.pj


@pytest.fixture(autouse=True)
def _stub_pj(monkeypatch):
    fake = types.ModuleType("fake_pj")
    fake.PJMEDIA_DIR_CAPTURE = 2
    monkeypatch.setattr(app_module, "pj", fake)
    yield
    monkeypatch.setattr(app_module, "pj", REAL_PJ)


def _mk_dev(dev_id, direction):
    return types.SimpleNamespace(id=dev_id, dir=direction, name=f"dev{dev_id}")


class _FakeVidDevManager:
    def __init__(self, devs):
        self.devs = devs

    def getDevCount(self):
        return len(self.devs)

    def enumDev2(self):
        return iter(self.devs)


class _FakeApp:
    config_data = {"video": {"device": 5}, "accounts": []}

    def __init__(self, devs):
        self.endpoint = types.SimpleNamespace(
            vidDevManager=lambda: _FakeVidDevManager(devs)
        )


class _FakeVideoConfig:
    autoShowIncoming = None
    autoTransmitOutgoing = None
    defaultCaptureDevice = None


class _FakeAccountConfig:
    def __init__(self):
        self.videoConfig = _FakeVideoConfig()


CAPTURE = 2  # PJMEDIA_DIR_CAPTURE no stub


def test_detect_prefers_saved_device():
    app = _FakeApp([_mk_dev(2, CAPTURE), _mk_dev(5, CAPTURE), _mk_dev(0, CAPTURE)])
    app_module.SoftphoneApp._detect_video_support(app)
    assert app._has_video is True
    assert app._video_workaround_dev == 5  # salvo presente

    acfg = _FakeAccountConfig()
    app_module.SoftphoneApp._apply_video_config(app, acfg)
    assert acfg.videoConfig.autoShowIncoming is True
    assert acfg.videoConfig.autoTransmitOutgoing is True
    assert acfg.videoConfig.defaultCaptureDevice == 5


def test_detect_fallback_to_zero_when_saved_missing():
    app = _FakeApp([_mk_dev(2, CAPTURE), _mk_dev(0, CAPTURE)])
    app_module.SoftphoneApp._detect_video_support(app)
    assert app._has_video is True
    assert app._video_workaround_dev == 0  # salvo (5) ausente -> 0


def test_detect_fallback_to_first_capture():
    app = _FakeApp([_mk_dev(3, CAPTURE), _mk_dev(4, CAPTURE)])
    app_module.SoftphoneApp._detect_video_support(app)
    assert app._has_video is True
    assert app._video_workaround_dev == 3  # salvo e 0 ausentes -> primeira


def test_detect_no_capture_devices_disables_auto():
    app = _FakeApp([_mk_dev(0, 1), _mk_dev(1, 1)])
    app_module.SoftphoneApp._detect_video_support(app)
    assert app._has_video is True
    assert app._video_workaround_dev == -1
    assert app._video_warning

    acfg = _FakeAccountConfig()
    app_module.SoftphoneApp._apply_video_config(app, acfg)
    assert acfg.videoConfig.autoShowIncoming is False
    assert acfg.videoConfig.autoTransmitOutgoing is False
    assert acfg.videoConfig.defaultCaptureDevice == -1


def test_detect_handles_no_devices():
    app = _FakeApp([])
    app_module.SoftphoneApp._detect_video_support(app)
    assert app._has_video is False
    assert app._video_workaround_dev == -1


def test_detect_handles_backend_errors():
    class Boom:
        def getDevCount(self):
            raise RuntimeError("boom")

        def enumDev2(self):
            raise RuntimeError("boom")

    app = _FakeApp([])
    app.endpoint = types.SimpleNamespace(vidDevManager=lambda: Boom())

    app_module.SoftphoneApp._detect_video_support(app)
    assert app._has_video is False
    assert app._video_workaround_dev == -1
