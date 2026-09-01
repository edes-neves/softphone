#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_pjsua2_codecs.py
-------------------------------------------------------------------------------
Teste de sanidade do módulo pjsua2 compilado para Python 3.14.4.

Executar DENTRO do venv onde o pjsua2 foi instalado:

    source venv/bin/activate
    python test_pjsua2_codecs.py

O script:
  1. Carrega o pjsua2;
  2. Cria um Endpoint e inicializa a biblioteca;
  3. Lista todos os codecs de áudio e vídeo disponíveis;
  4. Verifica explicitamente a presença de Opus, H.264 e VP8;
  5. Encerra a biblioteca de forma limpa.

Retorna código de saída != 0 se algum codec esperado estiver ausente.
-------------------------------------------------------------------------------
"""

from __future__ import annotations

import sys
import traceback


# Esperados (audio / video) para validar a compilação.
# IDs conforme codecEnum2()/videoCodecEnum2() do pjsua2 2.15.
EXPECTED_AUDIO = ("opus", "PCMU", "PCMA", "GSM", "speex", "iLBC", "G722", "G729")
EXPECTED_VIDEO = ("H264", "H263", "VP8", "VP9")

PJ_LIB_INIT_TRIES = 3


def banner(text: str) -> None:
    line = "=" * 70
    print(f"\n{line}\n{text}\n{line}")


def classify_codec(codec_id: str) -> tuple[str, str]:
    """Retorna (tipo, nome-curto). tipo = 'audio' ou 'video'."""
    cid = codec_id.strip()
    # Formato típico do PJSIP: "Opus/48000/2", "H264/90000", "VP8/90000", etc.
    head = cid.split("/", 1)[0]
    if "H26" in head or head.startswith("VP") or "MPEG" in head or head == "jpeg":
        return "video", head
    return "audio", head


def print_codecs(ep) -> tuple[list[str], list[str]]:
    audio: list[str] = []
    video: list[str] = []

    # pjsua2 >= 2.x expõe codecEnum2()/videoCodecEnum2(), que retornam
    # tuplas Python de CodecInfo (codecId, priority). O antigo codecEnum()
    # não existe mais no binding.
    try:
        infos = list(ep.codecEnum2()) + list(ep.videoCodecEnum2())
    except AttributeError:
        infos = getattr(ep, "codecEnum", lambda: [])()

    for info in infos:
        cid = getattr(info, "codecId", None) or str(info)
        kind, name = classify_codec(cid)
        prio = getattr(info, "priority", -1)
        disabled = " (DESATIVADO)" if prio == 0 else f" (prio={prio})"
        print(f"  [{kind:5s}] {cid}{disabled}")
        (audio if kind == "audio" else video).append(name.lower())

    return audio, video


def ensure(needles: tuple[str, ...], pool: list[str], label: str) -> bool:
    missing: list[str] = [n for n in needles if not any(n.lower() in c for c in pool)]
    if missing:
        print(f"\n  [FALTA] {label} esperado: {', '.join(missing)}")
        return False
    print(f"  [OK] {label} presente: {', '.join(needles)}")
    return True


def main() -> int:
    banner("TESTE pjsua2 — codecs de áudio e vídeo (Python "
           f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro})")

    # ---- 1. Import ---------------------------------------------------------
    try:
        import pjsua2 as pj
    except Exception:
        print("\n[ERRO] Não foi possível importar pjsua2.")
        print("Arquivo __file__ :", getattr(getattr(pj, "__file__", None), "name", "N/A"))
        traceback.print_exc()
        print("\nVerifique se o venv ativo é o mesmo onde o binding foi instalado.")
        return 2

    print("\nArquivo pjsua2 :", getattr(pj, "__file__", "(desconhecido)"))

    # ---- 2. Cria Endpoint e inicializa a lib -------------------------------
    ep = None
    try:
        ep = pj.Endpoint()
        print("Endpoint criado ............. OK")

        # libCreate pode lançar pj.Error em chamadas concorrentes; damos retry leve.
        last_err = None
        for attempt in range(1, PJ_LIB_INIT_TRIES + 1):
            try:
                ep.libCreate()
                break
            except pj.Error as e:
                last_err = e
                # Se já estava criada, siga em frente
                msg = str(getattr(e, "info", lambda: "")()) or str(e)
                if "already" in msg.lower():
                    break
                print(f"  tentativa {attempt}/{PJ_LIB_INIT_TRIES} libCreate falhou: {msg}")
        else:
            raise RuntimeError(f"libCreate falhou após {PJ_LIB_INIT_TRIES} tentativas: {last_err}")
        print("libCreate ................... OK")

        ep_cfg = pj.EpConfig()
        # Habilita judiciosamente para não encostar em hardware durante o teste:
        ep_cfg.logConfig.level = 4
        ep_cfg.logConfig.consoleLevel = 0
        ep.libInit(ep_cfg)
        print("libInit ..................... OK")

        # Transporte UDP efêmero (porta 0 = automática) só para a libStart.
        tcfg = pj.TransportConfig()
        tcfg.port = 0
        ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, tcfg)

        ep.libStart()
        print("libStart .................... OK")

        # ---- 3. Lista codecs ------------------------------------------------
        banner("CODECS DISPONÍVEIS NO BINDING")
        audio, video = print_codecs(ep)

        banner("VALIDAÇÃO DOS CODECS ESPERADOS")
        ok_a = ensure(EXPECTED_AUDIO, audio, "Áudio (Opus/...) ")
        ok_v = ensure(EXPECTED_VIDEO, video, "Vídeo (H.264/VP8)")

        # ---- 4. Análise extra de qualidade ---------------------------------
        def has_codec(name: str) -> bool:
            cid = name.lower()
            try:
                infos = list(ep.codecEnum2()) + list(ep.videoCodecEnum2())
            except Exception:
                return False
            return any(cid in (getattr(i, "codecId", str(i)).lower()) for i in infos)

        print("\nDetecções específicas:")
        for n in ("opus", "h264", "vp8"):
            print(f"  has_codec({n!r:8}) -> {has_codec(n)}")

    finally:
        # ---- 5. Shutdown limpo ---------------------------------------------
        if ep is not None:
            try:
                ep.libDestroy()
                print("\nlibDestroy .................. OK")
            except Exception as exc:
                print(f"\n[AVISO] libDestroy: {exc}")
            try:
                del ep
            except Exception:
                pass

    banner("RESULTADO FINAL")
    if ok_a and ok_v:
        print("  SUCESSO: todos os codecs esperados estão presentes.")
        return 0
    print("  FALHA: codecs esperados ausentes — revise as macros do config_site.h")
    print("         e a saída do ./configure.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")
        sys.exit(130)
