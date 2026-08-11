# Softphone SIP (tkinter + pjsua2)

Softphone para Linux usando a pilha VoIP PJSIP (`pjsua2`) com interface gráfica em
Tkinter. Suporta múltiplas contas SIP, registro automático, chamadas de saída,
chamadas de entrada (atender/recusar), mute, controle de volume e seleção de
dispositivos de áudio.

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
