# AGENTS.md

Guia para agentes/desenvolvedores que trabalham neste repositório
(**Voice Neves** — softphone SIP em PySide6/Qt + pjsua2).

## Visão geral

Aplicativo desktop Linux (com suporte experimental a Windows) que fala SIP usando
a pilha PJSIP (`pjsua2`) e desenha a UI com PySide6. O ponto de entrada é
`softphone.py`, que apenas chama `voice_neves.__main__.main()`.

## Ambiente e execução

- Python alvo: **3.12** (`target-version` no `ruff.toml`); o CI testa 3.11–3.14.
- Use sempre o virtualenv do projeto: `.venv/bin/python`.
- Rodar o app: `.venv/bin/python softphone.py`
- `pjsua2` **não** vem do pip; é carregado de `third_party/pjsip-dist/`
  (binding SWIG + `lib/lib*.so*`). Sem ele o app roda, mas as chamadas SIP ficam
  desativadas.

## Comandos essenciais (rodar SEMPRE antes de concluir uma tarefa)

```bash
# Testes (camada pura; pjsip/app pulam se pjsua2/display ausentes)
.venv/bin/python -m pytest -q

# Lint (mesmas regras do CI)
.venv/bin/ruff check voice_neves tests
```

- Esperado hoje: **158 passed, 5 skipped** e `ruff` limpo.
- Teste de integração SIP (pulado por padrão): `SIP_INTEGRATION_TEST=1 .venv/bin/python -m pytest tests/test_account_reregister_integration.py -v`

## Estrutura

| Caminho | Papel |
| --- | --- |
| `softphone.py` | Lançador fino → `voice_neves.__main__` |
| `voice_neves/app.py` | UI (PySide6) + controlador `SoftphoneApp`; arquivo **grande**, concentra quase toda a UI |
| `voice_neves/constants.py`, `themes.py`, `utils.py` | Camada pura (dados, validação, logging) |
| `voice_neves/config.py`, `history.py`, `secrets_store.py`, `contacts_store.py` | Persistência (config/histórico/segredos/contatos) |
| `voice_neves/pjsip_models.py`, `sip_backend.py` | Wrappers pjsua2 |
| `voice_neves/provisioning.py`, `updater.py` | Config remota e auto-atualização |
| `voice_neves/ldap_manager.py`, `cti.py` | Agenda LDAP e API CTI (opcionais) |
| `tests/` | Suíte pytest (camada pura + helpers de `app`) |
| `third_party/` | Fontes do PJSIP e `pjsip-dist/` (bindings/libs usados em runtime) |
| `build_pjsip.sh`, `build_exe.sh`, `packaging/` | Build do PJSIP, PyInstaller/AppImage e `.deb`/Flatpak |

## Convenções

- Estilo: o lint só checa E4/E7/E9/F/W (ver `ruff.toml`), com `line-length = 100`.
  `from .constants import *` é padrão (F403/F405 ignorados) e imports condicionais
  no topo são aceitos (E402).
- A camada pura **não** deve importar PySide6/pjsua2; mantenha-a testável.
- Preserve nomes/atributos antigos como aliases ao refatorar UI, para não quebrar
  pontos que já os referenciam (ex.: `video_preview_area`/`video_preview_frame`
  apontam para a mesma `video_surface`).
- Evite adicionar comentários supérfluos; o código já tem comentários explicativos
  em português nos pontos não óbvios.
- Mensagens de commit em português, no estilo do histórico (`fix:`, `feat:`,
  `chore:`, `build:`).

## Particularidades do PJSIP neste projeto (importante)

- O build atual usa o renderizador **SDL** (estaticamente ligado em
  `libpjmedia-videodev.so.2`); **não há renderizador X11**.
- O vídeo é embutido na UI criando a janela a partir do XID do widget Qt
  (`SDL_CreateWindowFrom`), via `_native_video_handle(xid)` /
  `_embed_video_window` em `app.py`.
- **Não existe suporte a espelhamento (*mirror*)** neste build: não há
  `VideoWindow.setMirror` nem capacidade equivalente em `pjmedia` (só rotação,
  `PJMEDIA_VID_DEV_CAP_ORIENTATION`). Não reintroduza o botão de espelhar sem
  antes adicionar suporte no PJSIP e recompilar.
- Prévia da câmera e vídeo da chamada compartilham a mesma área
  (`video_surface`) e nunca são exibidos ao mesmo tempo — ao iniciar um, o outro
  é encerrado com aviso (`_toggle_preview`, `_attach_remote_video`).

## Configuração e artefatos

- Config em `~/.config/softphone/config.json`; senhas no keyring (fallback
  `secrets.json` 0600). Ver README para a tabela XDG completa.
- **Não comitar artefatos de build** (`.deb`, `.AppImage`, `*.bak`, `dist/`,
  `build/`). O `.gitignore` já cobre os principais; adicione novos ao padrão.

## Build

- PJSIP: `./build_pjsip.sh` (grava em `third_party/pjsip-dist/`).
- Executável/AppImage: `./build_exe.sh` (precisa do passo acima).
- `.deb`/Flatpak: scripts em `packaging/`.
