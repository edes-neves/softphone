# Roteiro WSL2/Docker — rodar o VoiceNeves (com pjsua2/PJSIP completo) no Windows

Este roteiro te dá **chamadas SIP reais no Windows com o MENOR esforço**,
reaproveitando todo o build Linux do PJSIP 2.15 (G.729/BCG729, Opus, H.264,
VP8/VP9, SRTP, TLS) **sem recompilar nada**.

> Por que funciona: o softphone é uma GUI (PySide6) que usa o `pjsua2` (PJSIP)
> **compilado para Linux**. Rodando dentro do WSL2, o app é um programa Linux
> legítimo — o binding `.so` carrega normalmente. O WSL2 com **WSLg** entrega o
> display gráfico (X/Wayland) e o áudio (PulseAudio/PipeWire) para a UI
> aparecer e o som funcionar.

---

## Pré-requisitos (fazer 1 vez no Windows)

1. **Windows 10 (build 19044+) ou Windows 11** — o WSLg precisa da versão nova.
2. **WSL2 habilitado** com uma distro. Abra um **terminal PowerShell (admin)** e rode:

   ```powershell
   wsl --install -d Ubuntu-24.04
   ```

   Reinicie o PC quando pedir.

3. **Confirmar WSL2 + WSLg + áudio:**

   ```powershell
   wsl --version          # deve mostrar versão >= 2.0 e WSLg/Wayland
   wsl --set-default-version 2
   ```

   > O WSLg **já vem integrado** no WSL2 moderno — entrega X server,
   > Wayland e áudio (PulseAudio) automaticamente. **Não precisa instalar
   > um X server externo** (Xming/VcXsrv) para a UI aparecer.

---

## Passo 1 — Copiar o projeto para dentro do WSL

O teu projeto está em `C:\Users\edesn\dwhelper\Softphone`. Do WSL, os discos
do Windows aparecem montados em `/mnt/c/...`. O caminho fica:

```bash
/mnt/c/Users/edesn/dwhelper/Softphone
```

É **muito mais rápido e confiável trabalhar dentro do filesystem do WSL**
(`~`), e não em `/mnt/c` (que é lento). Vamos copiar para o home do WSL:

```bash
mkdir -p ~/softphone
cp -r /mnt/c/Users/edesn/dwhelper/Softphone/* ~/softphone/
cd ~/softphone
```

> Isso copia inclusive a pasta `.venv` se existir. No WSL vamos recriar o
> venv Linux para o Python certo (o `.venv` do Windows é inútil no Linux).

---

## Passo 2 — Instalar dependências de sistema no Ubuntu do WSL

```bash
sudo apt update
sudo apt install -y \
    python3 python3-venv python3-pip python3-pil \
    libasound2 libpulse0 pulseaudio \
    libssl3 libsrtp2-1 libopus0 libvpx7 \
    libavcodec-dev libavformat-dev libswscale-dev \
    libgl1 libegl1 libxkbcommon0 \
    notify-osd dbus-x11 \
    build-essential patchelf
```

> `libasound2`/`libpulse0` no HOST (WSL) é a pilha de som que o PJSIP usará —
> exatamente o que o `build_exe.sh` recomenda (cada SO usa a própria pilha).

---

## Passo 3 — Criar o virtualenv e instalar as dependências Python

**IMPORTANTE (leia antes):** o binding `pjsua2` é para **Python 3.14**. Você
tem duas trilhas possíveis — **escolha UMA**:

- **Trilha 3.14 (recomendada, sem recompilar):** siga o **Passo 4 → Opção A**
  abaixo, que já cria o venv com `python3.14`. Ignore este Passo 3.
- **Trilha 3.12 (Python padrão do Ubuntu):** faça este Passo 3 com `python3` e
  depois siga o **Passo 4 → Opção B** (recompilar o binding p/ 3.12).

Criando o venv (para a trilha 3.12, ou equivalente para 3.14 no Passo 4):

```bash
cd ~/softphone
python3 -m venv venv-linux
source venv-linux/bin/activate
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```

> `requirements.txt` instala PySide6, keyring, pystray, pynput, Pillow e
> pyinstaller. **Não** instala `pjsua2` (não é pip-installável) — a gente vai
> dar o binding manualmente no próximo passo.

---

## Passo 4 — Disponibilizar o `pjsua2` no venv do WSL

O projeto já tem o binding **compilado para Linux x86_64** em
`third_party/pjsip-opus-g729/python/`:

- `python/pjsua2.py`
- `python/_pjsua2.cpython-314-x86_64-linux-gnu.so`  ← **Python 3.14!**

### ⚠️ Atenção à versão do Python

O binding foi compilado para **CPython 3.14** (`...cpython-314...`). O Ubuntu
24.04 traz o **Python 3.12** por padrão. Duas opções:

#### Opção A (recomendada): usar Python 3.14 no WSL (via `pyenv`/`deadsnakes`)

```bash
# adiciona o PPA com Python 3.14
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.14 python3.14-venv python3.14-dev

# cria o venv 3.14 (substitui o de 3.12 se já criado) e instala as deps
python3.14 -m venv venv-linux
source venv-linux/bin/activate
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```

Depois coloque o binding no site-packages do venv **3.14**:

```bash
BUNDLE=~/softphone/voice_neves_pjsua2
mkdir -p "$BUNDLE"
cp third_party/pjsip-opus-g729/python/pjsua2.py "$BUNDLE/"
cp third_party/pjsip-opus-g729/python/_pjsua2.cpython-314-x86_64-linux-gnu.so "$BUNDLE/"
cp -L third_party/pjsip-opus-g729/lib/lib*.so* "$BUNDLE/" 2>/dev/null || true
patchelf --set-rpath '$ORIGIN' "$BUNDLE/_pjsua2.cpython-314-x86_64-linux-gnu.so"

# aponte o import para o bundle (por pathex/venv)
export PYTHONPATH="$BUNDLE"
```

#### Opção B: recompilar o binding para o Python 3.12 do Ubuntu

Se não quiser mexer com Python 3.14, rode o build do projeto no WSL:

```bash
cd ~/softphone
chmod +x build_pjsip.sh
PJSIP_DIR="$HOME/softphone/third_party/pjsip-opus-g729" \
PYBIN=/usr/bin/python3.12 \
VENV_DIR="$HOME/softphone/venv-linux" \
INSTALL_PREFIX="$HOME/softphone/install" \
./build_pjsip.sh
```

---

## Passo 5 — Rodar o app (com áudio)

### 1. Garantir display (WSLg) — normalmente automático

```bash
echo $DISPLAY            # deve imprimir algo como :0
echo $WAYLAND_DISPLAY    # deve imprimir algo como wayland-0
```

Se `DISPLAY` estiver vazio (WSLg não ativo), ative forçando:

```bash
export DISPLAY=:0
```

### 2. Garantir o áudio

O WSLg já sobe um servidor PulseAudio interno. Confira:

```bash
pactl info 2>/dev/null | grep "Server Name" || echo "pulse não visível"
```

Se não estiver, suba o PulseAudio na sessão:

```bash
pulseaudio --start 2>/dev/null || true
```

### 3. Rodar

```bash
cd ~/softphone
source venv-linux/bin/activate
export PYTHONPATH="$HOME/softphone/voice_neves_pjsua2"
python softphone.py
```

A janela do VoiceNeves deve abrir no desktop do Windows (via WSLg). Configure
sua conta SIP e ligue.

---

## Passo 6 — (Opcional) Gerar AppImage e rodar como app independente

Dentro do WSL, com o venv ativo:

```bash
cd ~/softphone
./build_exe.sh
```

Lembre-se de **remover as libs de áudio do sistema do pacote** (o próprio
script já faz isso), para que o app use a pilha do host.

Para rodar o app "autônomo" no WSL:

```bash
cd dist/VoiceNeves
./VoiceNeves
```

---

## Teste rápido de codecs (validar o build)

```bash
cd ~/softphone
source venv-linux/bin/activate
export PYTHONPATH="$HOME/softphone/voice_neves_pjsua2"
python test_pjsua2_codecs.py
```

Esperado: lista com **Opus, G729, PCMU, PCMA, GSM, Speex, iLBC, G722** (áudio) e
**H264, H263, VP8, VP9** (vídeo).

---

## Limitações reais a saber

| Item | Situação no WSL2/WSLg |
|------|------------------------|
| **Áudio SIP (voz)** | ✅ Funciona (PulseAudio/PipeWire do WSLg) |
| **Microfone** | ⚠️ Precisa acessar o dispositivo host; costuma funcionar via PulseAudio, mas às vezes exige `pam`/settings do WSLg. Teste com `arecord -l`. |
| **Vídeo de chamada (câmera)** | ⚠️ WSLg não expõe câmera nativamente. Pode precisar de `/dev/video*` redirecionado via `usbipd-win` (avançado) ou câmera virtual. |
| **Volume/notificações** | ✅ Volume do PulseAudio, notificações via notify-osd (precisa de `dbus-x11`). |

> **Dica de áudio se o microfone não aparecer:** rode o app com o PJSIP
> apontando para o dispositivo de som correto. No Linux do WSL, use
> `pactl list sources` e escolha no menu **Configurações → Áudio** do app.
> Em última instância, use o **modo "dispositivo nulo"** do bug de som já
> tratado no app (v1.0.2+), que evita falha silenciosa.

---

## Resolução de problemas

**1. Janela não abre (DISPLAY vazio)**
```bash
export DISPLAY=:0
export WAYLAND_DISPLAY=wayland-0
python softphone.py
```
Se persistir, reinicie o WSL:
```powershell
wsl --shutdown
```
e abra o app de novo.

**2. Erro `libpjsua2.so: cannot open shared object`**
Confira o `LD_LIBRARY_PATH` apontando para o bundle:
```bash
export LD_LIBRARY_PATH="$HOME/softphone/voice_neves_pjsua2"
```

**3. `_pjsua2...so` não compatível (undefined symbol / ABI)**
Quase sempre é **Python errado**. Certifique-se de estar usando o **3.14**
(caso do binding `cpython-314`). Veja Opção B para recompilar p/ o seu Python.

**4. Sem som nas chamadas mas o app abre**
É o problema ALSA→PipeWire. No Ubuntu do WSL (que usa o PipeWire do WSLg),
instale os maperas se precisar e reinicie o app:
```bash
sudo apt install -y pipewire pipewire-pulse pulseaudio-utils
pulseaudio --kill; pulseaudio --start
```

---

## Resumindo

O jeito **mais rápido e confiável** de ter chamadas SIP no Windows usando o
teu projecto, reaproveitando o PJSIP/BCG729 já compilado, é:

1. `wsl --install -d Ubuntu-24.04`
2. Copiar o projeto para `~/softphone`
3. `python3.14 -m venv` + `pip install -r requirements.txt`
4. Colocar o binding `pjsua2` (cpython-314) no `PYTHONPATH`
5. `export DISPLAY=:0` + `pulseaudio --start`
6. `python softphone.py`

Pronto — **G.729, Opus, SRTP, TLS e vídeo (o que o WSLg permitir) funcionando
dentro do Windows, sem compiler pjsua2 para Windows.**
