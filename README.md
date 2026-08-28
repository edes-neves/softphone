# Softphone SIP (PySide6/Qt + pjsua2)

Softphone para Linux usando a pilha VoIP PJSIP (`pjsua2`) com interface gráfica em
Qt (`PySide6`). Suporta múltiplas contas SIP, registro automático, chamadas de saída,
chamadas de entrada (atender/recusar), mute, controle de volume e seleção de
dispositivos de áudio.

## Estrutura do código

O projeto agora é um pacote `voice_neves/` (a aplicação monolítica
`softphone.py` virou um lançador fino). A camada de **lógica pura** foi separada
e é testável sem `PySide6` nem `pjsua2`:

| Módulo                       | Responsabilidade                                            |
| ---------------------------- | ----------------------------------------------------------- |
| `voice_neves/constants.py`   | Caminhos XDG, regex, versão, codecs, fontes (`__all__`)     |
| `voice_neves/themes.py`      | Paletas claro/escuro (somente dados)                        |
| `voice_neves/utils.py`       | `clean_extension`, validação, `build_sip_target`, logging   |
| `voice_neves/config.py`      | Carregar/salvar/normalizar `config.json` (migração legada)  |
| `voice_neves/history.py`    | Histórico de chamadas (I/O JSON)                            |
| `voice_neves/secrets_store.py` | Cofre de senhas (keyring + fallback `0600`)                |
| `voice_neves/contacts_store.py` | Contatos locais (`contacts.json`)                        |
| `voice_neves/ldap_manager.py` | Agenda corporativa LDAP com cache (opcional)                |
| `voice_neves/pjsip_models.py` | Wrappers pjsua2: `MyAccount`/`MyBuddy`/`MyCall`            |
| `voice_neves/runtime.py`    | Singleton do cofre de senhas                                |
| `voice_neves/provisioning.py` | Auto-provisioning: config remota (JSON) + cache offline    |
| `voice_neves/updater.py`    | Atualização automática: version.json + download/checksum    |
| `voice_neves/app.py`         | UI (PySide6/Qt) + controlador `SoftphoneApp` + globais de cor   |
| `voice_neves/__main__.py`    | Ponto de entrada (`main()`)                                 |

As globais mutáveis de cor (`COLOR_*`) permanecem no `app.py` (mesmo módulo da
UI), preservando o `set_theme()` do original.

## Testes e CI

```bash
pip install pytest pytest-cov
python -m pytest tests -q
python -m pytest tests --cov=voice_neves --cov-report=term-missing
```

Os testes cobrem a camada pura (constants, themes, utils, config, history,
secrets_store, contacts_store, platform, sip_backend) e pulam
`pjsip_models`/`app` quando `pjsua2` ou display não estão disponíveis. O CI
(`.github/workflows/ci.yml`) roda em Python 3.11–3.14: lint, smoke-import da
camada pura e pytest; há job extra para Windows e macOS validando que o app
carrega (sem pjsua2) e os testes da camada pura passam.

## Suporte multi-plataforma (cross-platform)

O app é **multi-plataforma na camada de UI e lógica pura**:

- **Linux**: funcionalidade completa, including G.729/BCG729, ZRTP, vídeo, LDAP.
- **Windows e macOS**: o app abre, configura contas, edita contatos/histórico,
  aplica tema claro/escuro e persiste config/contatos/histórico. **Chamadas SIP
  ficam desativadas** — ao tentar ligar, mostra *"Backend SIP indisponível
  neste sistema"* e o status exibe *"Backend SIP indisponível"*.

Por quê? O `pjsua2` é uma **binding C++ SWIG** do PJSIP — o binário produzido é
`.so` (ELF Linux) e não carrega em `.pyd` (Windows) nem `.dylib` (macOS). O
G.729 grátis (BCG729) está compilado dentro de `libpjmedia-codec.so`. Para
chamadas reais em Win/Mac seria preciso (a) cross-compile do pjsua2 com
BCG729 (grande esforço, risco de perda do codec) ou (b) outro backend SIP
(pip-installável, ex.: `linphone-sdk` — alternativo, sem G.729).

**Ganchos para o futuro** (já prontos, sem work extra):

- `voice_neves/sip_backend.py` — probe de disponibilidade (`import_pjsua2()`).
- `voice_neves/platform.py` — paths/notifica/diretório de música por SO.
- `app.py` — todo fluxo que usa `pj.*` está travado por `if self._sip_available`,
  `if self.endpoint is None`, etc. Plugar um novo backend futuramente só pede
  implementar `import_pjsua2()` para devolvê-lo.

Paths por SO (respeitando convenção nativa):

| SO       | Config                                              | Dados                                              |
| -------- | --------------------------------------------------- | -------------------------------------------------- |
| Linux    | `~/.config/softphone` (ou `$XDG_CONFIG_HOME/...`)   | `~/.local/share/softphone` (ou `$XDG_DATA_HOME`)  |
| macOS    | `~/Library/Application Support/softphone`           | igual ao de config                                 |
| Windows  | `%APPDATA%\softphone`                               | `%LOCALAPPDATA%\softphone`                         |

Notificações: `notify-send` (Linux), `osascript display notification` (macOS),
log (Windows — toast real via pywin32/winrt fica como gancho futuro).

Gravações de chamada: `~/Music/VoiceNeves` em qualquer SO (ou
`$XDG_MUSIC_HOME` no Linux), em vez do antigo `~/Música/...` que quebrava em
locais não-pt-BR.

## Dependências

- **Python 3.14+** (com Tkinter)
- **PJSIP/pjsua2 2.14** — não é distribuído via pip. Compile o PJSIP ou instale
  o pacote pré-compilado no site-packages do sistema (ex.: egg do pjsua2).

  O `softphone.py` importa `pjsua2` direto do ambiente. Se usar um `venv`, aponte
   o `pathex` do spec para o diretório do egg (veja `VoiceNeves.spec`).

- **keyring** (opcional, recomendado) — armazena as senhas no cofre do sistema
  (Secret Service/KWallet). Sem keyring, o app cai para um arquivo `secrets.json`
  local com permissão `0600`.

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt   # pyinstaller + keyring
```

## Executar (desenvolvimento)

```bash
python3 softphone.py
```

## Configuração

A configuração fica fora do diretório do app, seguindo a especificação XDG:

| Item               | Caminho                                   |
| ------------------ | ----------------------------------------- |
| Config             | `~/.config/softphone/config.json` (0600)  |
| Senhas (fallback)  | `~/.config/softphone/secrets.json` (0600) |
| Histórico          | `~/.local/share/softphone/history.json`   |
| Contatos           | `~/.local/share/softphone/contacts.json`  |
| Log                | `~/.local/share/softphone/app.log`        |

Senhas **não** são gravadas no `config.json` — ficam no keyring (ou no fallback
`secrets.json` com permissão 0600).

Na primeira execução, o app migra automaticamente um antigo `sip_config.json`
presente no diretório atual: limpa ramais inválidos (ex.: emojis no usuário),
remove duplicatas, move as senhas para o armazenamento seguro e apaga o arquivo
original.

## Gerar o binário (PyInstaller)

O spec espera o egg do pjsua2 em `/usr/local/lib/python3.14/dist-packages/pjsua2-2.14-*.egg`
e o libpjsua2 em `/usr/local/lib`. Ajuste `PJSUA2_EGG` e `PJSUA2_LIB` no
`VoiceNeves.spec` se o caminho diferir na sua máquina.

```bash
venv/bin/pyinstaller VoiceNeves.spec --noconfirm --clean
```

O executável é gerado em `dist/VoiceNeves/VoiceNeves`.

## Gerar o AppImage (portátil)

O AppImage empacota o binário PyInstaller junto com todas as dependências,
podendo ser executado em qualquer distribuição Linux sem instalar nada.

```bash
# Baixa o appimagetool
curl -sL -o /tmp/appimagetool https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x /tmp/appimagetool

# Monta o AppDir a partir do build do PyInstaller
rm -rf /tmp/AppDir && mkdir -p /tmp/AppDir/usr/bin /tmp/AppDir/usr/lib /tmp/AppDir/usr/share/applications /tmp/AppDir/usr/share/icons/hicolor/512x512/apps
cp -r dist/VoiceNeves /tmp/AppDir/usr/lib/VoiceNeves
cp dist/VoiceNeves/VoiceNeves /tmp/AppDir/usr/bin/
cp VoiceNeves.desktop /tmp/AppDir/usr/share/applications/
cp VoiceNeves.desktop /tmp/AppDir/
cp Icone.png /tmp/AppDir/Icone.png
cp Icone.png /tmp/AppDir/usr/share/icons/hicolor/512x512/apps/Icone.png

# O AppRun é obrigatório: sem ele o runtime falha com "execv error"
cat > /tmp/AppDir/AppRun <<'EOF'
#!/bin/sh
SELF="${APPDIR:-$(dirname "$(readlink -f "$0")")}/usr/lib/VoiceNeves/VoiceNeves"
exec "$SELF" "$@"
EOF
chmod +x /tmp/AppDir/AppRun

# Gera o AppImage (fora do AppDir, para o arquivo não se auto-embutir)
mkdir -p /tmp/AppImageOut
cd /tmp/AppImageOut
ARCH=x86_64 /tmp/appimagetool /tmp/AppDir
```

O resultado sai em `Voice_Neves-x86_64.AppImage`. Basta dar permissão de
execução e rodar (ou copiar para `~/.local/bin`, integrar com o AppImageLauncher,
etc.).

## Funcionalidades

- Registro SIP de múltiplas contas com indicador de status (online/registrando/offline)
- Chamadas de saída usando a conta selecionada na lista (fallback: primeira online)
- Chamadas de entrada com botão **Atender** e estado de chamada na tela
- Mute de microfone, volume de saída e entrada
- Seleção de dispositivos de áudio (entrada/saída)
- Tema claro/escuro (menu **Exibir → Tema Escuro**), persistido na configuração
- Codec G.729 (grátis) via BCG729, embutido estaticamente no `libpjmedia-codec.so`
- Logs detalhados em arquivo (`app.log`)

## Provisionamento e Atualização automática

### Auto-provisioning (config remota)

O app pode sincronizar contas (e opcionalmente Segurança/NAT) a partir de uma
config remota servida em JSON, ideal para implantação corporativa: o servidor
dita os ramais e a política, e o app as aplica. Acesse
**Config. → Provisionamento e Atualização**: habilite, informe a URL e o
intervalo de sincronização (5–1440 min). As contas provisionadas são
**mescladas** com as locais (por `user@server`); senhas vão para o cofre.
Um **cache local** guarda o último sync válido e é usado como *fallback
offline*, além de ser aplicado na inicialização.

Formato do JSON servido:

```json
{
  "version": 3,
  "accounts": [
    {"user": "100", "server": "sip.exemplo.com", "password": "segredo",
     "forward_unconditional": "", "forward_busy": "199",
     "forward_no_answer": "", "forward_no_answer_timeout": 20}
  ],
  "security": {"srtp": "optional"},
  "nat": {"ice": true, "stun_server": "stun.exemplo.com"}
}
```

Opcionalmente, `auth_user` + senha (HTTP Basic) autenticam a busca; a senha é
guardada no cofre (keyring) sob a chave `provision_auth`.

### Atualização automática

O app pode checar novas versões, baixar e validar (SHA-256) o novo binário.
Na inicialização (e periodicamente), o app consulta um `version.json` e avisa
se houver versão nova. A URL do arquivo é informada em **Config. →
Provisionamento e Atualização** (campo "URL version.json").

**Via GitHub (padrão):** o workflow `release.yml` publica o AppImage e o
`version.json` a cada release com **tag** (ex.: `v1.1.0`), commitando o arquivo
no branch `master`. O app já vem configurado com a URL estável **por padrão**:

```
https://raw.githubusercontent.com/edes-neves/softphone/master/version.json
```

Basta criar a tag `v<versão>` e o GitHub faz o resto (AppImage + sha256 real).
Qualquer outra URL (próprio servidor/NAS) também funciona — o app não depende
de GitHub.

Formato do `version.json`:

```json
{
  "version": "1.1.0",
  "url": "https://github.com/edes-neves/softphone/releases/download/v1.1.0/VoiceNeves-x86_64.AppImage",
  "sha256": "<sha256-hex-do-arquivo>"
}
```

Por segurança, o download é baixado para uma pasta temporária e **validado**
(SHA-256 quando presente); o app mostra onde o arquivo ficou e orienta a
substituir o binário/app atual e reiniciar (não sobrescreve um binário em
execução, evitando corromper o app).



## Solução de problemas (áudio)

### BigLinux / Manjaro / Arch-based: chamadas mudas ou erro ao ligar

**Sintomas**: chamadas recebidas conectam sem som e, ao originar chamada,
aparece erro do pjsua2 apontando para `src/pjsua2/call.cpp` (`makeCall`).

**Causa**: o PJSIP usa a pilha ALSA da distribuição, que no BigLinux é um
redirecionamento para o PipeWire. Se o mapeamento ALSA→PipeWire não estiver
instalado/configurado, o PJSIP não consegue abrir o dispositivo `default`
(o app abre o dispositivo de som **antes** de enviar o INVITE).

**Correção no sistema** (uma vez só, requer reiniciar o Voice Neves depois):

```bash
sudo pacman -S pipewire-alsa alsa-plugins alsa-utils
```

Teste fora do app (ambos devem rodar sem erro — use Ctrl+C para encerrar):

```bash
arecord -D default -f cd /dev/null
aplay -D default /dev/null
```

**A partir da v1.0.2**, o app detecta esse problema na inicialização: tenta
abrir o dispositivo padrão, faz fallback automático para outro dispositivo que
funcione e, se nada abrir, avisa na tela em vez de falhar silenciosamente
na hora da chamada.

Se persistir, verifique também:

1. Em **Configurações → Áudio**, escolha outro dispositivo de captura/reprodução.
2. Confirme que o PipeWire está saudável: `wpctl status`.
3. Envie o log do PJSIP (`~/.local/share/softphone/pjsua.log`) ao suporte.

No Ubuntu 22.04–26.04 não é necessário nenhum passo extra.

## Suporte a G.729 (BCG729)

O codec G.729 (8 kbit/s) é patenteado — o PJSIP não o inclui por padrão. Este
projeto compila o PJSIP 2.14 com o [BCG729](https://github.com/BelledonneCommunications/bcg729)
(incluído no `third_party` do PJSIP), habilitado em `pjlib/include/pj/config_site.h`:

```c
#define PJMEDIA_HAS_G729_CODEC 1
```

Para reproduzir o build do PJSIP:

```bash
./configure --with-bcg729
make dep && make -j$(nproc)
sudo make install && sudo ldconfig
```

O BCG729 é embutido **estaticamente** em `libpjmedia-codec.so`, então o binário
PyInstaller e o AppImage não ganham dependência extra. Para confirmar que o G.729
está ativo:

```bash
nm -D /usr/local/lib/libpjmedia-codec.so | grep -i bcg729
```

Na tela **Codecs** do app, `G729/8000/1` (e a variante com VAD/CNG `G729B/8000/1`)
aparecem na lista com prioridade editável.
