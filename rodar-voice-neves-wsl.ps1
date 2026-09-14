<#
.SYNOPSIS
  Automatiza a execução do VoiceNeves (softphone SIP PySide6 + pjsua2/PJSIP
  Linux) no Windows via WSL2 + WSLg, reutilizando o binding pjsua2 já
  compilado (CPython 3.14) — SEM recompilar o PJSIP.

.DESCRIPTION
  Passos automatizados (do guia WSL2-COMO-RODAR.md):
    1. Garante o WSL2 + WSLg (instala se faltar; pede reinício quando preciso).
    2. Instala Ubuntu-24.04 se ainda não houver distro.
    3. Copia o projeto do Windows para ~/softphone dentro do WSL.
    4. Instala deps de sistema (apt) + Python 3.14 (PPA deadsnakes).
    5. Cria o venv 3.14, instala requirements.txt.
    6. Monta o bundle pjsua2 (pjsua2.py + _pjsua2...so + lib*.so*).
    7. Opcional: roda o app.

.PARAMETER SkipWslSetup
  Não tenta instalar/configurar o WSL (útil se já está pronto). Só configura o
  projeto dentro do WSL existente.

.PARAMETER RunApp
  Ao final, executa o softphone dentro do WSL (abre a GUI).

.PARAMETER RebuildBinding
  Recompila o binding pjsua2 para o Python PADRÃO do Ubuntu (3.12) via
  build_pjsip.sh, se você não quiser a trilha Python 3.14.

.EXAMPLE
  .\rodar-voice-neves-wsl.ps1 -RunApp

.EXAMPLE
  .\rodar-voice-neves-wsl.ps1 -SkipWslSetup -RunApp
#>
[CmdletBinding()]
param(
    [switch]$SkipWslSetup,
    [switch]$RunApp,
    [switch]$RebuildBinding
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Constantes / configuração
# ---------------------------------------------------------------------------
$WslDistro = 'Ubuntu-24.04'
$WslDistroArg = '-d Ubuntu-24.04'
$ProjectWin = (Get-Location).Path               # pasta do projeto no Windows
$WslHome    = '~/softphone'                     # destino dentro do WSL
$BundleName = 'voice_neves_pjsua2'              # pasta do bundle pjsua2

function Write-Step   { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok     { param([string]$m) Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn   { param([string]$m) Write-Host "  [!] $m" -ForegroundColor Yellow }
function Write-Fatal  { param([string]$m) Write-Host "  [ERRO] $m" -ForegroundColor Red; exit 1 }

function Test-Administrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p  = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ---------------------------------------------------------------------------
# 0. Banner
# ---------------------------------------------------------------------------
Write-Host "===========================================================" -ForegroundColor Magenta
Write-Host "  VoiceNeves no Windows via WSL2/WSLg (pjsua2/PJSIP Linux)" -ForegroundColor Magenta
Write-Host "===========================================================" -ForegroundColor Magenta
Write-Host ("Projeto Windows : {0}" -f $ProjectWin)
Write-Host ("Distro WSL      : {0}" -f $WslDistro)
Write-Host ""

# ---------------------------------------------------------------------------
# Helper: executa um comando DENTRO do WSL (na distro padrão)
# ---------------------------------------------------------------------------
function Invoke-Wsl {
    param([string]$Command)
    & wsl --distribution $WslDistro -- bash -lc $Command 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "comando WSL falhou (exit=$LASTEXITCODE): $Command"
        return $false
    }
    return $true
}

# ---------------------------------------------------------------------------
# 1. Garantir WSL2 + WSLg
# ---------------------------------------------------------------------------
if (-not $SkipWslSetup) {
    Write-Step "PASSO 1/6 - Garantir WSL2 + WSLg"

    # Detecta se o WSL está instalado de forma robusta: `wsl.exe` pode
    # "lançar" um erro NativeCommandError quando não existe, abortando o
    # script com $ErrorActionPreference='Stop'. Usamos try/catch + stderr.
    $wslInstalled = $false
    try {
        $null = & wsl --version 1>$null 2>&1  # stderr capturado, sem abortar
        if ($LASTEXITCODE -eq 0) { $wslInstalled = $true }
    } catch {
        $wslInstalled = $false
    }

    if (-not $wslInstalled) {
        Write-Host "  WSL não encontrado. Instalando (requer administrador)..."
        if (-not (Test-Administrator)) {
            Write-Fatal "Instalar o WSL exige um terminal ADMINISTRADOR. Rode este script como admin, ou rode antes: wsl --install"
        }
        Start-Process -FilePath "$env:WINDIR\system32\wsl.exe" -ArgumentList '--install' -Wait -NoNewWindow
        Write-Warn "WSL instalado. PODE SER NECESSÁRIO REINICIAR O WINDOWS e rodar o script de novo."
        Write-Host "  Continuando (sudo do WSL pedirá o usuário/senha do novo Linux)..."
    } else {
        Write-Ok "WSL2 presente (versão acima). WSLg/áudio normalmente já embutidos."
    }

    # Garante WSL2 como padrão (tolerante a erros)
    try { & wsl --set-default-version 2 2>$null | Out-Null } catch { }
    Write-Ok 'wsl --set-default-version 2 aplicado (se suportado).'
}

# ---------------------------------------------------------------------------
# 2. Garantir a distro Ubuntu-24.04
# ---------------------------------------------------------------------------
Write-Step "PASSO 2/6 - Garantir a distro $WslDistro"

$hasDistro = & wsl --list --quiet 2>$null | Select-String -SimpleMatch 'Ubuntu-24.04'
if (-not $hasDistro) {
    Write-Host "  Distro $WslDistro não encontrada. Instalando (primeiro boot configura usuário/senha)..."
    & wsl --install -d Ubuntu-24.04 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Fatal "Falha ao instalar a distro. Tente reiniciar o Windows e rodar de novo."
    }
    Write-Warn "Primeiro boot: defina o usuário/senha do Ubuntu quando pedido."
    Write-Warn "Se houve reinício do WSL, recarregue o script."
} else {
    Write-Ok "Distro $WslDistro já instalada."
}

# Aguarda o WSL responder (pode estar iniciando)
Write-Host "  Aguardando o WSL iniciar..."
Start-Sleep -Seconds 5

# ---------------------------------------------------------------------------
# 3. Copiar o projeto para o WSL
# ---------------------------------------------------------------------------
Write-Step "PASSO 3/6 - Copiar projeto para $WslHome"

if (-not (Invoke-Wsl "mkdir -p $WslHome"))   { Write-Fatal "Não foi possível criar $WslHome no WSL." }
$drive = ($ProjectWin -replace ':.*$','').ToLowerInvariant()
$winPath = $ProjectWin -replace '^[A-Za-z]:','' -replace '\\','/'
if (-not (Invoke-Wsl "cp -r /mnt/$drive$winPath/. $WslHome/")) {
    Write-Warn "cp de /mnt/c falhou; tentando via tar/stream..."
    # fallback: empacota no lado Windows e extrai no WSL
    $tmpTar = Join-Path $env:TEMP "voiceneves-src.tar"
    if (Test-Path $tmpTar) { Remove-Item $tmpTar -Force }
    # 'tar' nativo do Windows 10+ consegue criar .tar
    & tar -C $ProjectWin -cf $tmpTar .
    if ($LASTEXITCODE -ne 0) { Write-Fatal "Falha ao empacotar o projeto ($ProjectWin)." }
    if (-not (Invoke-Wsl "mkdir -p $WslHome && tar -xf $tmpTar -C $WslHome")) {
        Write-Fatal "Falha ao extrair o projeto no WSL."
    }
}
Write-Ok "Projeto copiado para $WslHome"

# ---------------------------------------------------------------------------
# 4. Dependências de sistema + Python 3.14
# ---------------------------------------------------------------------------
Write-Step "PASSO 4/6 - Instalar dependências de sistema e Python 3.14"

$aptPackages = 'python3 python3-venv python3-pip python3-pil libasound2 libpulse0 ' +
               'pulseaudio libssl3 libsrtp2-1 libopus0 libvpx7 libavcodec-dev ' +
               'libavformat-dev libswscale-dev libgl1 libegl1 libxkbcommon0 ' +
               'notify-osd dbus-x11 build-essential patchelf software-properties-common'

if (-not $RebuildBinding) {
    # Trilha 3.14 (recomendada): usa o binding já compilado
    Write-Host "  Configurando PPA deadsnakes para Python 3.14..."
    if (-not (Invoke-Wsl "sudo apt-get update -qq && sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt-get update -qq")) {
        Write-Warn "Falha ao adicionar PPA deadsnakes. Tentando apenas pacotes base."
    }
    $aptPackages += ' python3.14 python3.14-venv python3.14-dev'
}

if (-not (Invoke-Wsl "sudo apt-get install -y $aptPackages")) {
    Write-Fatal "Falha ao instalar pacotes apt no WSL. Reveja a mensagem acima."
}
Write-Ok "Dependências de sistema instaladas."

# ---------------------------------------------------------------------------
# 5. venv + requirements
# ---------------------------------------------------------------------------
Write-Step "PASSO 5/6 - Criar venv e instalar requirements.txt"

$pyBin = if ($RebuildBinding) { 'python3' } else { 'python3.14' }

if (-not (Invoke-Wsl "cd $WslHome && $pyBin -m venv venv-linux")) {
    Write-Fatal "Falha ao criar o venv (python $pyBin). O Python 3.14 está instalado? ($RebuildBinding => python3)"
}
if (-not (Invoke-Wsl "cd $WslHome && source venv-linux/bin/activate && pip install --upgrade pip wheel setuptools && pip install -r requirements.txt")) {
    Write-Fatal "Falha ao instalar requirements.txt no venv."
}
Write-Ok "venv criado e requirements instalados."

# ---------------------------------------------------------------------------
# 6. Bundle pjsua2 (ou rebuild)
# ---------------------------------------------------------------------------
Write-Step "PASSO 6/6 - Montar o bundle pjsua2 no venv"

if ($RebuildBinding) {
    Write-Host "  Recompilando o binding pjsua2 para o Python padrão ($pyBin)..."
    if (-not (Invoke-Wsl "cd $WslHome && chmod +x build_pjsip.sh && PJSIP_DIR=$WslHome/third_party/pjsip-opus-g729 PYBIN=/usr/bin/$pyBin VENV_DIR=$WslHome/venv-linux INSTALL_PREFIX=$WslHome/install ./build_pjsip.sh")) {
        Write-Fatal "Falha ao recompilar o binding. Reveja a saída do build_pjsip.sh."
    }
    Write-Ok "Binding pjsua2 recompilado e instalado no venv."
} else {
    # Trilha 3.14: usa os binários já compilados do projeto
    $bundle = "$WslHome/$BundleName"
    $srcPy   = "$WslHome/third_party/pjsip-opus-g729/python"
    $srcLib  = "$WslHome/third_party/pjsip-opus-g729/lib"

    $setupBundle = @"
cd $WslHome
mkdir -p $bundle
cp $srcPy/pjsua2.py $bundle/
cp $srcPy/_pjsua2.cpython-314-x86_64-linux-gnu.so $bundle/
cp -L $srcLib/lib*.so* $bundle/ 2>/dev/null || true
patchelf --set-rpath '\$ORIGIN' $bundle/_pjsua2.cpython-314-x86_64-linux-gnu.so || true
# instala no site-packages do venv para achar via `import pjsua2`
SITE=\$(venv-linux/bin/python -c 'import site; print(site.getsitepackages()[0])')
cp $bundle/pjsua2.py \$SITE/
cp $bundle/_pjsua2.cpython-314-x86_64-linux-gnu.so \$SITE/
cp $bundle/lib*.so* \$SITE/ 2>/dev/null || true
echo BUNDLE_READY
"@
    if (-not (Invoke-Wsl $setupBundle)) {
        Write-Warn "Falha ao montar o bundle pjsua2 no WSL."
    } else {
        # confirma que o binding .so apareceu no site-packages do venv
        $found = & wsl $WslDistroArg -- bash -lc "ls \$($WslHome)/venv-linux/lib/python3.14/site-packages/_pjsua2*.so 2>/dev/null" 2>$null
        if ($found -match 'so') {
            Write-Ok "Bundle pjsua2 montado em $bundle e copiado para o site-packages."
        } else {
            Write-Warn "O .so do pjsua2 não foi encontrado no site-packages — confira a trilha Python 3.14."
        }
    }
}

# ---------------------------------------------------------------------------
# Validação final + rodar
# ---------------------------------------------------------------------------
Write-Step "Validação do pjsua2 dentro do WSL"

# Script bash alimentado via stdin (bash -s) para não conflitar com o parser
# PowerShell (que rejeita `&&`, `<<` e quebras de linha em strings simples).
$checkScript = @"
source $WslHome/venv-linux/bin/activate
python - <<'PY'
import sys
try:
    import pjsua2
    print('PY', sys.version.split()[0], 'pjsua2 OK (importado):', pjsua2.__file__)
    sys.exit(0)
except Exception as e:
    print('PY', sys.version.split()[0], 'FALHA', e)
    sys.exit(1)
PY
"@
$ver = $checkScript | & wsl $WslDistroArg -- bash -s 2>&1
Write-Host "  $ver"

if ($LASTEXITCODE -eq 0) {
    Write-Ok "pjsua2 importável no WSL."
} else {
    Write-Warn "O módulo pjsua2 ainda não importa no WSL. Reanalise o Passo 6."
}

Write-Host ""
Write-Host "===========================================================" -ForegroundColor Magenta
Write-Host "  SETUP CONCLUÍDO NO WSL" -ForegroundColor Green
Write-Host "===========================================================" -ForegroundColor Magenta

if ($RunApp) {
    Write-Step "Rodando o VoiceNeves (GUI via WSLg)..."
    Write-Host "  Se a janela não abrir, verifique DISPLAY / pulseaudio (guia WSL2-COMO-RODAR.md)."
    $envCmd = if ($RebuildBinding) { "" } else { "export PYTHONPATH='$WslHome/$BundleName'; " }
    & wsl $WslDistroArg -- bash -lc "cd $WslHome && source venv-linux/bin/activate && $envCmd python softphone.py"
} else {
    Write-Host ""
    Write-Host "Pronto para rodar manualmente. No WSL:"
    Write-Host "    wsl -d $WslDistro"
    Write-Host "    cd $WslHome && source venv-linux/bin/activate"
    if (-not $RebuildBinding) { Write-Host "    export PYTHONPATH=$WslHome/$BundleName" }
    Write-Host "    python softphone.py"
    Write-Host ""
    Write-Host "Para já abrir a GUI via WSLg agora, rode de novo com:"
    Write-Host "    .\$($MyInvocation.MyCommand.Name) -RunApp"
}
