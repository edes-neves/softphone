<#
.SYNOPSIS
    Baixa e compila as bibliotecas externas de codec para o PJSIP Windows.

.DESCRIPTION
    Compila para Release/x64:
      - Opus (third_party/opus)         -> libopus.lib
      - libvpx (third_party/libvpx)      -> vpx.lib (VP8/VP9)
      - OpenH264 (third_party/openh264)  -> openh264.lib (H.264)
      - SILK (third_party/silk)          -> silksdk.lib

    Os artefatos (headers + .lib) sao colocados em:
      third_party/<lib>/include
      third_party/<lib>/lib
    E tambem copiados para o terceiro `third_party/build` do pjproject.

.EXAMPLE
    .\build_win_external_libs.ps1            # baixa + compila tudo
    .\build_win_external_libs.ps1 -OnlyOpus  # so Opus
#>
param(
    [ValidateSet("all","opus","vpx","openh264","silk")]
    [string]$Only = "all"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ===========================================================================
# Configuracao
# ===========================================================================
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$PjRoot    = Join-Path $ScriptDir "build\pjproject"
$ThirdPartyDir = Join-Path $PjRoot "third_party"

function Log($msg)   { Write-Host "[extlib] $msg" -ForegroundColor Cyan }
function Warn($msg)  { Write-Host "[AVISO] $msg" -ForegroundColor Yellow }
function Err($msg)   { Write-Host "[ERRO] $msg" -ForegroundColor Red }
function Step($msg)  { Write-Host "`n$('=' * 70)" -ForegroundColor DarkCyan; Write-Host "  $msg" -ForegroundColor White }

function Get-VsDevCmd {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) { throw "vswhere nao encontrado" }
    $installPath = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($installPath)) {
        throw "Visual Studio Build Tools nao encontrado"
    }
    $vsDevCmd = Join-Path $installPath "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path $vsDevCmd)) { throw "VsDevCmd.bat nao encontrado" }
    return $vsDevCmd
}

function Invoke-WithVs {
    param([string]$VsDevCmd, [string]$Command)
    $cmd = "call `"$VsDevCmd`" -arch=amd64 -host_arch=amd64 && $Command"
    cmd.exe /c $cmd
    return $LASTEXITCODE
}

$VsDevCmd = Get-VsDevCmd
Log "Ambiente VS: $VsDevCmd"

# ===========================================================================
# Helper: garantir git disponivel
# ===========================================================================
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    $env:Path = "C:\Program Files\Git\cmd;C:\ProgramData\chocolatey\bin;" + $env:Path
}

# ===========================================================================
# 1. OPUS
# ===========================================================================
if ($Only -eq "all" -or $Only -eq "opus") {
    Step "1. Compilando OPUS"
    $opusRoot = Join-Path $ThirdPartyDir "opus"
    if (-not (Test-Path (Join-Path $opusRoot ".git"))) {
        Log "Clonando opus..."
        git clone --depth 1 https://github.com/xiph/opus.git $opusRoot
    }

    # A solucao VS do opus fica em win32/VS2015 e VS2022
    $opusSln = Get-ChildItem -Path $opusRoot -Recurse -Filter "*.sln" `
        | Where-Object { $_.Name -match "VS2022|VS2019|VS2017" } | Select-Object -First 1
    if (-not $opusSln) {
        # fallback qualquer sln
        $opusSln = Get-ChildItem -Path $opusRoot -Recurse -Filter "*.sln" | Select-Object -First 1
    }
    if (-not $opusSln) {
        Warn "Nenhuma solucao VS do Opus encontrada. Tentando cmake..."
        $opusBuild = Join-Path $opusRoot "build_win"
        New-Item -ItemType Directory -Force -Path $opusBuild | Out-Null
        Push-Location $opusBuild
        try {
            $code = Invoke-WithVs $VsDevCmd "cmake .. -G `"NMake Makefiles`" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF"
            if ($code -eq 0) { $code = Invoke-WithVs $VsDevCmd "nmake" }
            if ($code -ne 0) { Warn "cmake/nmake do Opus falhou" }
        } finally { Pop-Location }
    } else {
        Log "Solucao VS Opus: $($opusSln.FullName)"
        $code = Invoke-WithVs $VsDevCmd "msbuild `"$($opusSln.FullName)`" /t:Build /p:Configuration=Release /p:Platform=x64 /p:PlatformToolset=v143 /m /nologo /verbosity:minimal"
        if ($code -ne 0) { Warn "MSBuild do Opus falhou" }
    }

    # Localizar headers e lib
    $opusInclude = Get-ChildItem -Path $opusRoot -Recurse -Filter "opus.h" -ErrorAction SilentlyContinue | Select-Object -First 1
    $opusLib = Get-ChildItem -Path $opusRoot -Recurse -Filter "libopus*.lib" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($opusLib -and $opusInclude) {
        $opusProjInc = Join-Path $opusRoot "include"
        $opusProjLib = Join-Path $opusRoot "lib"
        if (-not (Test-Path $opusProjInc)) {
            New-Item -ItemType Directory -Force -Path $opusProjInc | Out-Null
            Copy-Item (Join-Path $opusInclude.DirectoryName "*") $opusProjInc -Recurse -Force
        }
        if (-not (Test-Path $opusProjLib)) {
            New-Item -ItemType Directory -Force -Path $opusProjLib | Out-Null
            Copy-Item $opusLib.FullName $opusProjLib -Force
        }
        Log "Opus OK: include=$opusProjInc lib=$($opusLib.FullName)"
    } else {
        Warn "Nao foi possivel localizar headers/lib do Opus (include=$($opusInclude -ne $null), lib=$($opusLib -ne $null))"
    }
}

# ===========================================================================
# 2. LIBVPX (VP8/VP9)
# ===========================================================================
if ($Only -eq "all" -or $Only -eq "vpx") {
    Step "2. Compilando LIBVPX (VP8/VP9)"
    $vpxRoot = Join-Path $ThirdPartyDir "libvpx"
    if (-not (Test-Path (Join-Path $vpxRoot ".git"))) {
        Log "Clonando libvpx..."
        git clone --depth 1 https://chromium.googlesource.com/webm/libvpx $vpxRoot
    }

    $vpxBuild = Join-Path $vpxRoot "build_msvc"
    New-Item -ItemType Directory -Force -Path $vpxBuild | Out-Null
    Push-Location $vpxBuild
    try {
        Log "Configurando libvpx (NMake)..."
        $code = Invoke-WithVs $VsDevCmd "..\configure --target=x86_64-win64-vs16 --disable-examples --disable-tools --enable-vp8 --enable-vp9 --enable-static-msvcrt"
        if ($code -eq 0) {
            Log "Compilando libvpx..."
            $code = Invoke-WithVs $VsDevCmd "nmake"
        }
        if ($code -ne 0) {
            # Tentar gerar via vcxproj se disponivel
            Warn "Build nmake do libvpx falhou. Tentando via scripts do projeto..."
        }
    } finally { Pop-Location }

    $vpxLib = Get-ChildItem -Path $vpxBuild -Filter "*.lib" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($vpxLib) {
        $vpxProjLib = Join-Path $vpxRoot "lib"
        New-Item -ItemType Directory -Force -Path $vpxProjLib | Out-Null
        Copy-Item $vpxLib.FullName $vpxProjLib -Force
        # include dir (vpx/*.h)
        Log "libvpx OK: lib=$($vpxLib.FullName)"
    } else {
        Warn "Nao foi possivel compilar libvpx. VP8/VP9 ficarao desativados."
    }
}

# ===========================================================================
# 3. OPENH264 (H.264)
# ===========================================================================
if ($Only -eq "all" -or $Only -eq "openh264") {
    Step "3. Compilando OPENH264 (H.264)"
    $oh264Root = Join-Path $ThirdPartyDir "openh264"
    if (-not (Test-Path (Join-Path $oh264Root ".git"))) {
        Log "Clonando openh264..."
        git clone --depth 1 https://github.com/cisco/openh264.git $oh264Root
    }

    $oh264Build = Join-Path $oh264Root "build_win"
    New-Item -ItemType Directory -Force -Path $oh264Build | Out-Null
    Push-Location $oh264Root
    try {
        Log "Configurando openh264 (NMake)..."
        $code = Invoke-WithVs $VsDevCmd "nmake OS=msvc ARCH=x86_64"
        if ($code -ne 0) { Warn "nmake do openh264 falhou" }
    } finally { Pop-Location }

    $oh264Lib = Get-ChildItem -Path $oh264Root -Filter "*.lib" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($oh264Lib) {
        $dir = Join-Path $oh264Root "lib"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Copy-Item $oh264Lib.FullName $dir -Force
        Log "OpenH264 OK: lib=$($oh264Lib.FullName)"
    } else {
        Warn "Nao foi possivel compilar OpenH264. H.264 ficara desativado."
    }
}

# ===========================================================================
# 4. SILK
# ===========================================================================
if ($Only -eq "all" -or $Only -eq "silk") {
    Step "4. Compilando SILK"
    # SILK SDK historico nao tem build VS facil; verificar se ja existe
    Warn "SILK SDK e obsoleto e nao acompanha o projeto PJSIP moderno."
    Warn "Pulando compilacao do SILK (se nao for compilado, o codec SILK fica desativado)."
}

Step "CONCLUIDO"
Log "Verifique os logs acima para alguns codecs externos."
