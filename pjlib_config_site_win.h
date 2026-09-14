/*
 * config_site.h — Voice Neves Windows build
 *
 * Audio codecs (nativos): PCMU, PCMA, G722, L16, G7221, GSM, Speex, iLBC
 * Audio codec externo:    Opus (compilado via third_party/opus)
 * G.729 (BCG729), SILK, VP8/VP9, H.263, H.264: desativados (libs externas
 *   nao disponiveis na compilacao nativa MSVC deste checkout)
 * Security:        SRTP, TLS/SSL (Schannel nativo no Windows)
 * Features:        Video (captura/render DShow), ICE, STUN, TURN, IPv6,
 *                  WebRTC AEC, conferencias
 */

#ifndef __PJ_CONFIG_SITE_H__
#define __PJ_CONFIG_SITE_H__

/* ======================================================================
 * Seguranca: TLS/SSL e SRTP
 * ====================================================================== */
#define PJ_HAS_SSL_SOCK          1
#define PJMEDIA_HAS_SRTP         1

/*
 * No Windows, o TLS usa o Schannel nativo (sem dependencia externa de
 * OpenSSL). Em Linux/Unix, o PJSIP usa OpenSSL (default = PJ_SSL_SOCK_IMP_OPENSSL).
 */
#ifdef _WIN32
#  define PJ_SSL_SOCK_IMP        PJ_SSL_SOCK_IMP_SCHANNEL
#endif

/* ======================================================================
 * Codecs de audio
 * ====================================================================== */
/* G.711 (built-in) */
#define PJMEDIA_HAS_G711_CODEC   1

/* G.722 (built-in) */
#define PJMEDIA_HAS_G722_CODEC   1

/* L16 (built-in) */
#define PJMEDIA_HAS_L16_CODEC    1

/* G.722.1 (built-in) */
#define PJMEDIA_HAS_G7221_CODEC  1

/* GSM (via third_party/gsm) */
#define PJMEDIA_HAS_GSM_CODEC    1

/* Speex (via third_party/speex) */
#define PJMEDIA_HAS_SPEEX_CODEC  1

/* iLBC (via third_party/ilbc) */
#define PJMEDIA_HAS_ILBC_CODEC   1

/* SILK (via third_party/silk) - SDK obsoleto, nao compila em MSVC moderno */
#define PJMEDIA_HAS_SILK_CODEC   0

/* Opus (via third_party/opus) */
#define PJMEDIA_HAS_OPUS_CODEC   1

/* G.729 (via BCG729 SDK externo em third_party/bcg729) */
/* A macro correta do PJSIP e PJMEDIA_HAS_BCG729 (nao _CODEC).
   bcg729.lib compilado para MSVC x64 em third_party/lib. */
#define PJMEDIA_HAS_G729_CODEC   1
#define PJMEDIA_HAS_BCG729       1

/* AMR-NB (via opencore-amr — requires external build) */
/* #define PJMEDIA_HAS_AMR_CODEC 1 */

/* ======================================================================
 * Codecs de video
 * ======================================================================
 * ATENCAO: O build MSVC do PJSIP 2.15 NAO inclui codigo-fonte de codecs de
 * video (sem diretorio pjmedia-videocodec). Os codecs H263/VP8/VP9 exigem
 * libs externas. Usamos OpenH264 (H.264) e libvpx (VP8/VP9). Compilamos
 * libvpx (ShiftMediaProject msvc17, estatico) e BCG729 para MSVC x64.
 * VP8/VP9: libvpx.lib + headers em third_party/libvpx/include/vpx.
 * ====================================================================== */
#define PJMEDIA_HAS_VIDEO        1
#define PJSUA_HAS_VIDEO          1

/* H.263 (sem fonte no build MSVC) */
#define PJMEDIA_HAS_H263_CODEC   0

/* H.264 via OpenH264 (DLL prebuilt do Cisco + import lib) */
#define PJMEDIA_HAS_OPENH264_CODEC 1

/* libyuv: conversor de cores (YUY2->I420) necessario para a previ da
 * camera DShow. Sem ele, pjmedia_vid_port NAO encontra converter
 * (PJ_ENOTFOUND) e a previs video nao inicia. */
#define PJMEDIA_HAS_LIBYUV       1

/* VP8/VP9 via libvpx (ShiftMediaProject libvpx.lib estatico, msvc17) */
#define PJMEDIA_HAS_VPX_CODEC    1
#define PJMEDIA_HAS_VPX_CODEC_VP8 1
#define PJMEDIA_HAS_VPX_CODEC_VP9 1

/* MPEG4 via FFmpeg/libav (externo) */
/* #define PJMEDIA_HAS_FFMPEG    1 */
/* #define PJMEDIA_HAS_MPEG4_CODEC 1 */

/* ======================================================================
 * Audio device / middleware
 * ====================================================================== */
#define PJMEDIA_HAS_SOUND        1
#define PJMEDIA_AUDIO_DEV_HAS_WMME  1
#define PJMEDIA_AUDIO_DEV_HAS_WASAPI 0
#define PJMEDIA_AUDIO_DEV_HAS_DSOUND 1

/* WebRTC AEC */
#define PJMEDIA_HAS_WEBRTC_AEC   1

/* ======================================================================
 * Rede e NAT traversal
 * ====================================================================== */
#define PJ_HAS_IPV6              1
#define PJNATH_HAS_ICE           1
#define PJNATH_HAS_STUN          1
#define PJNATH_HAS_TURN          1

/* ======================================================================
 * Limites e performance
 * ====================================================================== */
#define PJ_IOQUEUE_MAX_HANDLES   2048
#define PJ_CONFIG_MAX_CALLS      64
#define PJSUA_MAX_ACC            16
#define PJSUA_MAX_BUDDIES        64

/* ======================================================================
 * Windows-specific
 * ====================================================================== */
#ifdef _WIN32
  /* DirectSound e MME para Windows */
  #define PJMEDIA_AUDIO_DEV_HAS_DIRECTSOUND 1
  /* DirectShow para capture de video */
  #define PJMEDIA_VIDEO_DEV_HAS_DSHOW 1
  /* SDL2 para renderizacao de video (preview + video remoto em janela nativa).
   * sem renderer, pjsua_vid_preview_start falha com PJMEDIA_EVID_NODEFDEV.
   * headers em third_party/sdl2/include; SDL2.lib em third_party/lib. */
  #define PJMEDIA_VIDEO_DEV_HAS_SDL 1
#endif

#endif /* __PJ_CONFIG_SITE_H__ */
