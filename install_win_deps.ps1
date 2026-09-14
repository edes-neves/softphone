<#
.SYNOPSIS
    Instala todas as dependencias necessarias para compilar o PJSIP no Windows.

.DESCRIPTION
    Instala:
      - Visual Studio Build Tools 2022 (compilador MSVC x64)
      - SWIG (gerador de bindings)
      - Git (clone do pjproject)
      - OpenSSL para Windows (TLS/SSL)
      - Python development headers

    Requer execucao como Administrador.
    O Chocolatey e usado para instalacao automatizada.

.EXAMPLE
    # Execute como Administrador:
    .\install_win_deps.ps1
#>
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Log($msg)  { Write-Host "[install] $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "[AVISO] $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "[ERRO] $msg" -ForegroundColor Red }
function Step($msg) { Write-Host "`n$('=' * 70)" -ForegroundColor DarkCyan; Write-Host "  $msg" -ForegroundColor White }

# ===========================================================================
# Verificar privilegios de Administrador
# ===========================================================================
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    Err "Este script precisa ser executado como Administrador."
    Err "Clique com botao direito no PowerShell e selecione 'Executar como administrador'."
    exit 1
}

# ===========================================================================
# Passo 1: Chocolatey
# ===========================================================================
Step "1. Verificando/instalando Chocolatey"
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
    Log "Instalando Chocolatey..."
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar Chocolatey" }
    # Atualizar PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}
Log "Chocolatey OK."

# ===========================================================================
# Passo 2: Git
# ===========================================================================
Step "2. Verificando/instalando Git"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Log "Instalando Git..."
    choco install -y git
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}
Log "Git: $(git --version)"

# ===========================================================================
# Passo 3: SWIG
# ===========================================================================
Step "3. Verificando/instalando SWIG"
if (-not (Get-Command swig -ErrorAction SilentlyContinue)) {
    Log "Instalando SWIG..."
    choco install -y swig
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}
Log "SWIG: $(swig -version 2>&1 | Select-String 'SWIG Version' | Select-Object -First 1)"

# ===========================================================================
# Passo 4: Visual Studio Build Tools 2022
# ===========================================================================
Step "4. Verificando/instalando Visual Studio Build Tools 2022"
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
$hasVS = $false
if (Test-Path $vswhere) {
    $p = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($p)) {
        $hasVS = $true
        Log "Visual Studio encontrado: $p"
    }
}

if (-not $hasVS) {
    Log "Instalando Visual Studio Build Tools 2022..."
    Log "Isso pode levar 15-30 minutos (download de ~3-5 GB)..."

    # Instalar via winget ou choco
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Microsoft.VisualStudio.2022.BuildTools `
            --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended" `
            --accept-source-agreements --accept-package-agreements
    } else {
        choco install -y visualstudio2022buildtools `
            --package-parameters "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
    }

    # Verificar novamente
    $hasVS = $false
    if (Test-Path $vswhere) {
        $p = & $vswhere -latest -products * `
            -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
            -property installationPath 2>$null
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($p)) {
            $hasVS = $true
        }
    }
    if (-not $hasVS) {
        throw "Visual Studio Build Tools nao foi instalado corretamente."
    }
    Log "Visual Studio Build Tools instalado."
}

# ===========================================================================
# Passo 5: OpenSSL para Windows
# ===========================================================================
Step "5. Verificando OpenSSL para Windows"
$sslFound = $false
foreach ($p in @(
    "C:\Program Files\OpenSSL",
    "C:\Program Files (x86)\OpenSSL",
    "$env:USERPROFILE\scoop\apps\openssl\current"
)) {
    if (Test-Path $p) {
        Log "OpenSSL encontrado: $p"
        $sslFound = $true
        break
    }
}
if (-not $sslFound) {
    Log "Instalando OpenSSL..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id ShiningLightPoint.OpenSSL --accept-source-agreements --accept-package-agreements
    } else {
        choco install -y openssl
    }
    Log "OpenSSL instalado."
}

# ===========================================================================
# Passo 6: Python headers (ja incluido no Python 3.13)
# ===========================================================================
Step "6. Verificando Python development headers"
$pyInc = & python -c "import sysconfig; print(sysconfig.get_path('include'))" 2>$null
if (Test-Path $pyInc) {
    Log "Python include: $pyInc"
} else {
    Warn "Headers do Python nao encontrados. Reinstale o Python com 'development headers' habilitado."
}

# ===========================================================================
# Resumo
# ===========================================================================
Step "TODAS AS DEPENDENCIAS INSTALADAS!"
Log ""
Log "Proximo passo: Execute o script de build:"
Log "  .\build_pjsip_win.ps1"
Log ""
Log "Ou com opcoes:"
Log "  .\build_pjsip_win.ps1 -Clean       # limpa build anterior"
Log "  .\build_pjsip_win.ps1 -SkipBuild    # reaproveita build existente"
Log "  .\build_pjsip_win.ps1 -PjsipVersion 2.14  # versao especifica"
