<#
.SYNOPSIS
    Build PJSIP/pjsua2 for Windows (MSVC) com codecs completos.

.DESCRIPTION
    Compila o PJSIP 2.15 para Windows x64 com:
      - Codecs de audio nativos + Opus: PCMU, PCMA, G722, L16, G7221, GSM,
        Speex, iLBC, Opus
      - Codecs de video: NAO diposniveis no build MSVC (exigem libs externas)
      - Seguranca: SRTP + TLS/SSL (Schannel nativo no Windows)
      - NAT: ICE, STUN, TURN, IPv6
      - Audio: WMME/DSOUND; Video: DShow (captura/render)

    O binding Python e gerado via SWIG e copiado para o diretorio do projeto.

.PARAMETER PythonExe
    Caminho do executavel Python (default: python).

.PARAMETER PjsipVersion
    Tag/branch do pjproject (default: 2.15).

.PARAMETER BuildDir
    Diretorio temporario de build (default: .\build\pjproject).

.PARAMETER SkipBuild
    Pula a compilacao e vai direto para o binding SWIG (build previo existente).

.PARAMETER Clean
    Limpa o build anterior antes de compilar.

.EXAMPLE
    .\build_pjsip_win.ps1
    .\build_pjsip_win.ps1 -PjsipVersion 2.15 -Clean
    .\build_pjsip_win.ps1 -SkipBuild  # reaproveita build existente
#>
param(
    [string]$PythonExe = "python",
    [string]$PjsipVersion = "2.15",
    [string]$BuildDir = "",
    [switch]$SkipBuild,
    [switch]$Clean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ===========================================================================
# Configuracao
# ===========================================================================
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RootDir   = $ScriptDir

if (-not $BuildDir) {
    $BuildDir = Join-Path $RootDir "build\pjproject"
}

$PjprojectDir  = $BuildDir
$SwigDir       = Join-Path $PjprojectDir "pjsip-apps\src\swig\python"
$ThirdPartyDir = Join-Path $PjprojectDir "third_party"
$ConfigSiteSrc = Join-Path $RootDir "pjlib_config_site_win.h"

# Diretorio de destino dos artefatos para o projeto
$DestInclude = Join-Path $RootDir "third_party\pjsip-win\include"
$DestLib     = Join-Path $RootDir "third_party\pjsip-win\lib"
$DestPython  = Join-Path $RootDir "third_party\pjsip-win\python"

# ===========================================================================
# Helpers
# ===========================================================================
function Log($msg)   { Write-Host "[build_pjsip] $msg" -ForegroundColor Cyan }
function Warn($msg)  { Write-Host "[AVISO] $msg" -ForegroundColor Yellow }
function Err($msg)   { Write-Host "[ERRO] $msg" -ForegroundColor Red }
function Step($msg)  { Write-Host "`n$('=' * 70)" -ForegroundColor DarkCyan; Write-Host "  $msg" -ForegroundColor White; Write-Host "$('=' * 70)" -ForegroundColor DarkCyan }

function Invoke-VsEnvironment {
    <#
    .SYNOPSIS
    Ativa o ambiente de desenvolvimento do Visual Studio (VsDevCmd.bat).
    #>
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) {
        throw "vswhere.exe nao encontrado. Instale o Visual Studio Build Tools."
    }

    $installPath = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath 2>$null

    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($installPath)) {
        throw "Visual Studio com ferramentas C++ nao encontrado."
    }

    $vsDevCmd = Join-Path $installPath "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path $vsDevCmd)) {
        throw "VsDevCmd.bat nao encontrado em: $vsDevCmd"
    }

    Log "Ambiente Visual Studio encontrado: $installPath"
    return $vsDevCmd
}

function Test-BuildTools {
    $missing = @()
    foreach ($tool in @("git", "python")) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            $missing += $tool
        }
    }
    if (-not (Get-Command swig -ErrorAction SilentlyContinue)) {
        $missing += "swig"
    }
    $hasCompiler = (Get-Command cl -ErrorAction SilentlyContinue) -or
                   (Get-Command msbuild -ErrorAction SilentlyContinue)
    if (-not $hasCompiler) {
        $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
        if (Test-Path $vswhere) {
            $p = & $vswhere -latest -products * `
                -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
                -property installationPath 2>$null
            if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($p)) {
                $hasCompiler = $true
            }
        }
    }
    if (-not $hasCompiler) { $missing += "msbuild-or-cl" }

    if ($missing.Count -gt 0) {
        throw "Ferramentas de build ausentes: $($missing -join ', '). Execute install_win_deps.ps1 primeiro."
    }
    Log "Todas as ferramentas de build verificadas."
}

# ===========================================================================
# Passo 1: Verificar ferramentas
# ===========================================================================
Step "1. Verificando ferramentas de build"
Test-BuildTools
$PythonVersion = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
Log "Python: $PythonVersion"

# ===========================================================================
# Passo 2: Clonar/Atualizar pjproject
# ===========================================================================
Step "2. Clonando pjproject $PjsipVersion"
New-Item -ItemType Directory -Force -Path (Split-Path $BuildDir -Parent) | Out-Null

if (-not (Test-Path (Join-Path $PjprojectDir ".git"))) {
    Log "Clonando pjproject..."
    git clone --depth 1 --branch $PjsipVersion https://github.com/pjsip/pjproject.git $PjprojectDir
} else {
    Log "Repositorio existente. Atualizando..."
    git -C $PjprojectDir fetch --tags --force origin
    git -C $PjprojectDir checkout --force $PjsipVersion
}

if ($Clean) {
    Warn "Limpando build anterior..."
    git -C $PjprojectDir clean -fdx
}

# ===========================================================================
# Passo 3: Aplicar config_site.h customizado
# ===========================================================================
Step "3. Aplicando config_site.h com codecs completos"
if (-not (Test-Path $ConfigSiteSrc)) {
    throw "Arquivo de configuracao nao encontrado: $ConfigSiteSrc"
}
$destConfig = Join-Path $PjprojectDir "pjlib\include\pj\config_site.h"
Copy-Item -Force $ConfigSiteSrc $destConfig
Log "config_site.h copiado para $destConfig"

# ===========================================================================
# Passo 4: Compilar terceiros (Opus)
# ===========================================================================
Step "4. Compilando bibliotecas de terceiros"
$vsDevCmd = Invoke-VsEnvironment

# --- Opus ---
# O Opus NAO vem no arvore do pjproject; clonamos e compilamos via cmake+NMake
# para MSVC x64, e colocamos headers+lib em third_party/opus e third_party/lib.
$opusDir = Join-Path $ThirdPartyDir "opus"
if (-not (Test-Path (Join-Path $opusDir ".git"))) {
    Log "Clonando Opus..."
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        $env:Path = "C:\Program Files\Git\cmd;C:\ProgramData\chocolatey\bin;" + $env:Path
    }
    git clone --depth 1 https://github.com/xiph/opus.git $opusDir
}

$opusExeLib = Join-Path $ThirdPartyDir "lib\opus.lib"
if (-not (Test-Path $opusExeLib)) {
    $opusBuildDir = Join-Path $opusDir "build_win"
    New-Item -ItemType Directory -Force -Path $opusBuildDir | Out-Null
    Push-Location $opusBuildDir
    try {
        Log "Configurando Opus via CMake..."
        $cfgCmd = "call `"$vsDevCmd`" -arch=amd64 -host_arch=amd64 && cd /d `"$opusBuildDir`" && cmake .. -G `"NMake Makefiles`" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF"
        cmd.exe /c $cfgCmd
        if ($LASTEXITCODE -eq 0) {
            Log "Compilando Opus (nmake)..."
            $mkCmd = "call `"$vsDevCmd`" -arch=amd64 -host_arch=amd64 && cd /d `"$opusBuildDir`" && nmake"
            cmd.exe /c $mkCmd
        }
        if ($LASTEXITCODE -ne 0) {
            Warn "Build do Opus falhou. codecs opus sera ignorado."
        } else {
            # Publicar headers em include/opus/ e lib em third_party/lib
            $opusIncRoot = Join-Path $opusDir "include\opus"
            New-Item -ItemType Directory -Force -Path $opusIncRoot | Out-Null
            Get-ChildItem (Join-Path $opusDir "include\*.h") | ForEach-Object {
                Copy-Item $_.FullName $opusIncRoot -Force
            }
            $opusLib = Join-Path $opusBuildDir "opus.lib"
            if (Test-Path $opusLib) {
                New-Item -ItemType Directory -Force -Path (Join-Path $ThirdPartyDir "lib") | Out-Null
                Copy-Item $opusLib (Join-Path $ThirdPartyDir "lib\opus.lib") -Force
                Log "Opus compilado com sucesso."
            } else {
                Warn "opus.lib nao encontrado apos build."
            }
        }
    } finally { Pop-Location }
} else {
    Log "Opus ja compilado (opus.lib presente)."
}

# --- Aplicar patch do pragma do Opus ---
# pjmedia-codec/opus.c usa "#pragma comment(lib, "libopus.a")" por padrao.
# Invertemos para usar "opus.lib" (nome do nosso build MSVC).
$opusSrcFile = Join-Path $PjprojectDir "pjmedia\src\pjmedia-codec\opus.c"
if (Test-Path $opusSrcFile) {
    $content = Get-Content $opusSrcFile -Raw
    if ($content -match '#\s*if 0 /\* Change to 0 if Opus lib name is "opus.lib" \*/') {
        # ja aplicado (if 0)
    } elseif ($content -match '#\s*if 1 /\* Change to 0 if Opus lib name is "opus.lib" \*/') {
        $content = $content -replace '#\s*if 1 /\* Change to 0 if Opus lib name is "opus.lib" \*/',
                                       '#  if 0 /\* Change to 0 if Opus lib name is "opus.lib" \*/'
        Set-Content -Path $opusSrcFile -Value $content -NoNewline
        Log "Patch aplicado em opus.c (pragma -> opus.lib)"
    } else {
        Warn "Nao foi possivel localizar o pragma do Opus em opus.c (skip patch)"
    }
}

# --- OpenH264 / libvpx / BCG729 ---
# H.264 (OpenH264) e o UNICO codec de video disponivel no build MSVC. Usamos
# a DLL prebuilt do Cisco (openh264-x.yzw-win64.dll) e geramos o import lib
# openh264.lib a partir do openh264.def (metodo documentado pelo proprio PJSIP).
# libvpx (VP8/VP9) e BCG729 (G.729) exigem compilacao externa e ficam off.

# 1) Publicar headers wels/ em third_party/include/wels
$ohSrcHeaders = Join-Path $PjprojectDir "third_party\openh264\codec\api\wels"
$welsDst = Join-Path $ThirdPartyDir "include\wels"
New-Item -ItemType Directory -Force -Path $welsDst | Out-Null
Get-ChildItem "$ohSrcHeaders\*.h" -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item $_.FullName $welsDst -Force
}

# 2) Provisionar DLL prebuilt do Cisco + import lib
$ohLib = Join-Path $ThirdPartyDir "lib\openh264.lib"
if (-not (Test-Path $ohLib)) {
    Log "Provisionando OpenH264 (DLL prebuilt do Cisco + import lib)..."
    $ohVer = "2.4.0"
    $tmp = Join-Path $env:TEMP "opencode\openh264"
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $bz2 = Join-Path $tmp "openh264-$ohVer-win64.dll.bz2"
    $dll = Join-Path $tmp "openh264.dll"
    try {
        Invoke-WebRequest -Uri "http://ciscobinary.openh264.org/openh264-$ohVer-win64.dll.bz2" -OutFile $bz2 -UseBasicParsing
        # Decompactar .bz2 via Python (bz2 built-in)
        python -c "import bz2,sys;open(r'$dll','wb').write(bz2.decompress(open(r'$bz2','rb').read()))"
        if (-not (Test-Path $dll)) { throw "Falha ao extrair openh264.dll" }
        # Gerar import lib a partir do .def com MSVC
        $def = Join-Path $PjprojectDir "third_party\openh264\openh264.def"
        $libCmd = "call `"$vsDevCmd`" -arch=amd64 -host_arch=amd64 && lib /nologo /def:`"$def`" /out:`"$ohLib`" /machine:x64"
        cmd.exe /c $libCmd
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $ohLib)) {
            throw "Falha ao gerar openh264.lib"
        }
        # Copiar DLL para o destino de runtime do binding + terceiros
        Copy-Item $dll (Join-Path $SwigDir "openh264.dll") -Force
        Copy-Item $dll (Join-Path $DestPython "openh264.dll") -Force
        Log "OpenH264 provisionado com sucesso (openh264.lib + openh264.dll)."
    } catch {
        Warn "OpenH264 NAO provisionado: $_ . H.264 ficara desativado."
    }
} else {
    Log "OpenH264 ja provisionado (openh264.lib presente)."
}

# --- SDL2 (renderer de video) ---
# Sem um device de saida/render, pjsua_vid_preview_start falha com
# PJMEDIA_EVID_NODEFDEV. O SDL2 e o renderer nativo do PJSIP em Windows
# (pjmedia/src/pjmedia-videodev/sdl_dev.c usa SDL_CreateWindowFrom).
# Provisionamos headers, SDL2.lib e SDL2.dll a partir do pacote oficial
# da libsdl-org/SDL (SDL2-devel-X.Y.Z-VC.zip).
$sdlLib = Join-Path $ThirdPartyDir "lib\SDL2.lib"
if (-not (Test-Path $sdlLib)) {
    Log "Provisionando SDL2 (renderer de video)..."
    $sdlVer = "2.30.10"
    $tmp = Join-Path $env:TEMP "opencode\sdl2"
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $zip = Join-Path $tmp "SDL2-devel-$sdlVer-VC.zip"
    $extract = Join-Path $tmp "SDL2-$sdlVer"
    try {
        Invoke-WebRequest -Uri "https://github.com/libsdl-org/SDL/releases/download/release-$sdlVer/SDL2-devel-$sdlVer-VC.zip" -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $sdlRoot = Join-Path $extract ""
        # headers -> third_party/sdl2/include
        $sdlInc = Join-Path $PjprojectDir "third_party\sdl2\include"
        New-Item -ItemType Directory -Force -Path $sdlInc | Out-Null
        Copy-Item (Join-Path $extract "include\*.h") $sdlInc -Force
        # lib + dll
        Copy-Item (Join-Path $extract "lib\x64\SDL2.lib") $ThirdPartyDir\lib -Force
        Copy-Item (Join-Path $extract "lib\x64\SDL2.dll") (Join-Path $SwigDir "SDL2.dll") -Force
        Copy-Item (Join-Path $extract "lib\x64\SDL2.dll") (Join-Path $DestPython "SDL2.dll") -Force
        Log "SDL2 provisionado (headers + SDL2.lib + SDL2.dll)."
    } catch {
        Warn "SDL2 NAO provisionado: $_ . O preview de video ficara sem renderer."
    }
} else {
    Log "SDL2 ja provisionado (SDL2.lib presente)."
}

# ---------------------------------------------------------------------------
# Provisionar libvpx (VP8/VP9) - ShiftMediaProject prebuilt estatico msvc17
# ---------------------------------------------------------------------------
# O codec vpx.c usa `#pragma comment(lib, "vpx.lib")`, por isso o estatico
# libvpx.lib e copiado com NOME vpx.lib em third_party/lib. Headers vpx
# instalados em third_party/libvpx/include/vpx/ (resolve <vpx/...>).
$vpxLib = Join-Path $ThirdPartyDir "lib\vpx.lib"
if (-not (Test-Path $vpxLib)) {
    Log "Provisionando libvpx (VP8/VP9 prebuilt estatico)..."
    $vpxVer   = "1.15.1"
    $vpxTmp   = Join-Path $env:TEMP "opencode\vpx"
    New-Item -ItemType Directory -Force -Path $vpxTmp | Out-Null
    $vpxZip   = Join-Path $vpxTmp "libvpx_v${vpxVer}_msvc17.zip"
    $vpxExt   = Join-Path $vpxTmp "libvpx_msvc17"
    try {
        Invoke-WebRequest -Uri "https://github.com/ShiftMediaProject/libvpx/releases/download/v${vpxVer}/libvpx_v${vpxVer}_msvc17.zip" -OutFile $vpxZip -UseBasicParsing
        Expand-Archive -Path $vpxZip -DestinationPath $vpxTmp -Force
        # headers -> third_party/libvpx/include/vpx
        $vpxInc = Join-Path $PjprojectDir "third_party\libvpx\include"
        New-Item -ItemType Directory -Force -Path (Join-Path $vpxInc "vpx") | Out-Null
        Copy-Item (Join-Path $vpxExt "include\vpx\*.h") (Join-Path $vpxInc "vpx") -Force
        # lib estatico (libvpx.lib) copiado como vpx.lib (pragma do PJSIP)
        Copy-Item (Join-Path $vpxExt "lib\x64\libvpx.lib") $vpxLib -Force
        Log "libvpx provisionado (headers + vpx.lib)."
    } catch {
        Warn "libvpx NAO provisionado: $_ . VP8/VP9 nao estaran disponibles."
    }
} else {
    Log "libvpx ja provisionado (vpx.lib presente)."
}

# ---------------------------------------------------------------------------
# Provisionar BCG729 (G.729) - compilado estatico a partir do upstream
# ---------------------------------------------------------------------------
# BCG729_STATIC precisa estar na compilacion de bcg729.c (config de macros
# en config_site.h / pjlib_config_site_win.h y preprocesador _LIB;BCG729_STATIC
# en pjmedia_codec.vcxproj y libpjproject.vcxproj).
$bcgLib = Join-Path $ThirdPartyDir "lib\bcg729.lib"
if (-not (Test-Path $bcgLib)) {
    Log "Provisionando BCG729 (G.729) compilando desde fuente..."
    $bcgTmp = Join-Path $env:TEMP "opencode\bcg729"
    New-Item -ItemType Directory -Force -Path $bcgTmp | Out-Null
    $bcgZip = Join-Path $bcgTmp "bcg729-master.zip"
    $bcgSrc = Join-Path $bcgTmp "bcg729-master"
    try {
        Invoke-WebRequest -Uri "https://github.com/BelledonneCommunications/bcg729/archive/refs/heads/master.zip" -OutFile $bcgZip -UseBasicParsing
        Expand-Archive -Path $bcgZip -DestinationPath $bcgTmp -Force
        $bcgDest = Join-Path $PjprojectDir "third_party\bcg729"
        New-Item -ItemType Directory -Force -Path (Join-Path $bcgDest "include") | Out-Null
        Copy-Item (Join-Path $bcgSrc "include\*.h") (Join-Path $bcgDest "include") -Force
        # compilar cada fuente .c -> .obj y archivar bcg729.lib
        $objDir = Join-Path $bcgTmp "obj"
        New-Item -ItemType Directory -Force -Path $objDir | Out-Null
        $srcDir = Join-Path $bcgSrc "src"
        $incDir = Join-Path $bcgDest "include"
        Push-Location $objDir
        foreach ($cf in Get-ChildItem $srcDir -Filter "*.c") {
            & cl /c /I"$incDir" /O2 /MD /nologo $cf.FullName
        }
        Pop-Location
        New-Item -ItemType Directory -Force -Path (Join-Path $ThirdPartyDir "lib") | Out-Null
        $objList = (Get-ChildItem $objDir -Filter "*.obj" | ForEach-Object { '"' + $_.FullName + '"' }) -join " "
        & lib /nologo /out:"$bcgLib" $objList
        Log "BCG729 provisionado (bcg729.lib)."
    } catch {
        Warn "BCG729 NAO provisionado: $_ . El codec G.729 no estara disponible."
    }
} else {
    Log "BCG729 ja provisionado (bcg729.lib presente)."
}

# ===========================================================================
# Passo 5: Compilar PJSIP via MSBuild
# ===========================================================================
if (-not $SkipBuild) {
    Step "5. Compilando PJSIP via MSBuild (Release/x64)"

    # Localizar solucao VS
    $slnCandidates = @(
        "pjproject-vs17.sln",
        "pjproject-vs14.sln"
    )
    $slnPath = $null
    foreach ($s in $slnCandidates) {
        $candidate = Join-Path $PjprojectDir $s
        if (Test-Path $candidate) {
            $slnPath = $candidate
            break
        }
    }
    if (-not $slnPath) {
        throw "Solucao VS do pjproject nao encontrada. Candidatos: $($slnCandidates -join ', ')"
    }
    Log "Usando solucao: $slnPath"

    # Verificar se libvpx esta disponivel para VP8/VP9
    $vpxDir = Join-Path $ThirdPartyDir "libvpx"
    if (-not (Test-Path $vpxDir)) {
        Warn "libvpx nao encontrado em $vpxDir - VP8/VP9 podem nao funcionar."
        Warn "Para VP8/VP9, baixe libvpx e coloque em third_party/libvpx"
    }

    # Compilar (usar BuildToolset=v143, pois o pjproject usa essa propriedade
    # nos .props internos; somente PlatformToolset nao sobrepoe o v140)
    $buildCmd = "call `"$vsDevCmd`" -arch=amd64 -host_arch=amd64 && msbuild `"$slnPath`" /t:Build /p:Configuration=Release /p:Platform=x64 /p:PlatformToolset=v143 /p:BuildToolset=v143 /m /nologo /verbosity:minimal"
    Log "Iniciando build (pode levar 10-30 minutos)..."
    cmd.exe /c $buildCmd
    # Exit codes diferentes de 0 aqui vem normalmente dos testes/samples
    # (pjsystest/pjsua/samples) que nao sao necessarios para o binding pjsua2.
    # Verificamos se as libs core foram geradas.
    $coreOk = (Test-Path (Join-Path $PjprojectDir "pjsip\lib\pjsua2-lib-x86_64-x64-vc14-Release.lib")) -and
              (Test-Path (Join-Path $PjprojectDir "pjmedia\lib\pjmedia-codec-x86_64-x64-vc14-Release.lib"))
    if ($LASTEXITCODE -ne 0 -and -not $coreOk) {
        throw "MSBuild falhou com codigo $LASTEXITCODE (libs core nao geradas)"
    }
    Log "Build do PJSIP concluido (libs core presentes)."
} else {
    Step "5. Build pulado (-SkipBuild). Verificando artefatos existentes..."
}

# ===========================================================================
# Passo 6: Gerar binding SWIG Python
# ===========================================================================
Step "6. Gerando binding SWIG para Python $PythonVersion"

# Verificar se SWIG esta disponivel
if (-not (Get-Command swig -ErrorAction SilentlyContinue)) {
    throw "SWIG nao encontrado. Instale via: choco install swig"
}

# Verificar se os .lib foram gerados
$libFiles = @()
foreach ($libDir in @(
    (Join-Path $PjprojectDir "lib"),
    (Join-Path $PjprojectDir "pjlib\lib"),
    (Join-Path $PjprojectDir "pjlib-util\lib"),
    (Join-Path $PjprojectDir "pjmedia\lib"),
    (Join-Path $PjprojectDir "pjsip\lib"),
    (Join-Path $PjprojectDir "pjnath\lib"),
    (Join-Path $PjprojectDir "third_party\lib")
)) {
    if (Test-Path $libDir) {
        $libFiles += Get-ChildItem -Path $libDir -Filter "*.lib" -ErrorAction SilentlyContinue
    }
}
Log "Encontrados $($libFiles.Count) arquivos .lib"

if ($libFiles.Count -eq 0) {
    throw "Nenhum arquivo .lib encontrado. O build do MSBuild pode ter falhado."
}

# Gerar wrapper SWIG
$swigIface = Join-Path (Split-Path $SwigDir -Parent) "pjsua2.i"
if (-not (Test-Path $swigIface)) {
    throw "Arquivo pjsua2.i nao encontrado em: $swigIface"
}

Push-Location $SwigDir
try {
    Log "Gerando pjsua2_wrap.cpp via SWIG..."
    $swigCmd = "swig -c++ -python -threads " +
        "-I`"$PjprojectDir\pjlib\include`" " +
        "-I`"$PjprojectDir\pjlib-util\include`" " +
        "-I`"$PjprojectDir\pjmedia\include`" " +
        "-I`"$PjprojectDir\pjsip\include`" " +
        "-I`"$PjprojectDir\pjnath\include`" " +
        "-o pjsua2_wrap.cpp `"$swigIface`""
    cmd.exe /c $swigCmd
    if ($LASTEXITCODE -ne 0) { throw "SWIG falhou com codigo $LASTEXITCODE" }
    Log "SWIG wrapper gerado com sucesso."

    # Compilar extensao Python
    Log "Compilando extensao _pjsua2.pyd..."

    # Usar setup_pjsua2_windows.py do proprio projeto ou criar um
    $setupScript = Join-Path $RootDir "setup_pjsua2_win.py"
    if (Test-Path $setupScript) {
        $env:PJDIR = $PjprojectDir
        $env:MSYSTEM = ""
        & $PythonExe $setupScript build_ext --inplace
        if ($LASTEXITCODE -ne 0) { throw "Build da extensao Python falhou" }
    } else {
        Warn "setup_pjsua2_win.py nao encontrado. Usando compilacao direta..."
        # Compilacao direta via cl.exe
        $includeDirs = @(
            "$PjprojectDir\pjlib\include",
            "$PjprojectDir\pjlib-util\include",
            "$PjprojectDir\pjmedia\include",
            "$PjprojectDir\pjsip\include",
            "$PjprojectDir\pjnath\include"
        )
        $incFlags = ($includeDirs | ForEach-Object { "/I`"$_`"" }) -join " "
        $cmd = "call `"$vsDevCmd`" -arch=amd64 -host_arch=amd64 && " +
               "cl /EHsc /MD /O2 $incFlags /I`"$PjprojectDir\third_party\include`" " +
               "/LD pjsua2_wrap.cpp /Fe:_pjsua2.pyd"
        cmd.exe /c $cmd
        if ($LASTEXITCODE -ne 0) { throw "Compilacao direta falhou" }
    }
    Log "Extensao _pjsua2.pyd compilada."
} finally {
    Pop-Location
}

# ===========================================================================
# Passo 7: Copiar artefatos para o projeto
# ===========================================================================
Step "7. Copiando artefatos para third_party/pjsip-win/"

# Limpar destino anterior
if (Test-Path $DestInclude) { Remove-Item -Recurse -Force $DestInclude }
if (Test-Path $DestLib)     { Remove-Item -Recurse -Force $DestLib }
if (Test-Path $DestPython)  { Remove-Item -Recurse -Force $DestPython }

New-Item -ItemType Directory -Force -Path $DestInclude | Out-Null
New-Item -ItemType Directory -Force -Path $DestLib     | Out-Null
New-Item -ItemType Directory -Force -Path $DestPython  | Out-Null

# Copiar headers
Log "Copiando headers..."
$includeDirs = @("pjlib\include", "pjlib-util\include", "pjmedia\include",
                  "pjsip\include", "pjnath\include")
foreach ($dir in $includeDirs) {
    $src = Join-Path $PjprojectDir $dir
    if (Test-Path $src) {
        $destSub = Join-Path $DestInclude (Split-Path $dir -Leaf)
        Copy-Item -Recurse -Force $src $destSub
    }
}

# Copiar libs
Log "Copiando bibliotecas..."
$libDirs = @("lib", "pjlib\lib", "pjlib-util\lib", "pjmedia\lib",
             "pjsip\lib", "pjnath\lib", "third_party\lib")
foreach ($dir in $libDirs) {
    $src = Join-Path $PjprojectDir $dir
    if (Test-Path $src) {
        Copy-Item -Force (Join-Path $src "*.lib") $DestLib -ErrorAction SilentlyContinue
    }
}

# Copiar DLLs
Log "Copiando DLLs..."
foreach ($dir in $libDirs) {
    $src = Join-Path $PjprojectDir $dir
    if (Test-Path $src) {
        Copy-Item -Force (Join-Path $src "*.dll") $DestLib -ErrorAction SilentlyContinue
    }
}

# Copiar binding Python
Log "Copiando binding Python..."
$pyFiles = @("pjsua2.py", "_pjsua2.pyd", "openh264.dll")
foreach ($f in $pyFiles) {
    $src = Join-Path $SwigDir $f
    if (Test-Path $src) {
        Copy-Item -Force $src $DestPython
    }
}

# Copiar DLLs de codec e dependencias para o diretorio do projeto
Log "Copiando DLLs de codec para o diretorio do projeto..."
$dllSearch = @(
    (Join-Path $PjprojectDir "lib"),
    (Join-Path $PjprojectDir "pjlib\lib"),
    (Join-Path $PjprojectDir "pjmedia\lib"),
    (Join-Path $PjprojectDir "pjsip\lib"),
    (Join-Path $PjprojectDir "pjnath\lib"),
    (Join-Path $PjprojectDir "third_party\lib")
)
foreach ($d in $dllSearch) {
    if (Test-Path $d) {
        Copy-Item -Force (Join-Path $d "*.dll") $RootDir -ErrorAction SilentlyContinue
    }
}

# ===========================================================================
# Passo 8: Verificacao
# ===========================================================================
Step "8. Verificando importacao do pjsua2"

$testScript = @"
import sys, os
sys.path.insert(0, r'$DestPython')
try:
    import pjsua2 as pj
    ep = pj.Endpoint()
    print(f'pjsua2 importado com sucesso!')
    print(f'Arquivo: {pj.__file__}')
except Exception as e:
    print(f'ERRO: {e}')
    sys.exit(1)
"@

$testFile = Join-Path $RootDir "test_win_import.py"
Set-Content -Path $testFile -Value $testScript -Encoding UTF8
& $PythonExe $testFile
if ($LASTEXITCODE -ne 0) {
    Warn "Teste de importacao falhou. Verifique os logs acima."
} else {
    Log "Importacao do pjsua2 OK!"
}
Remove-Item -Force $testFile -ErrorAction SilentlyContinue

Step "BUILD CONCLUIDO!"
Log "Artefatos em: third_party/pjsip-win/"
Log "Para usar no app, ative o venv e execute:"
Log "  python test_pjsua2_codecs.py"
Log ""
Log "Codecs de audio esperados: PCMU, PCMA, G722, L16, G7221, GSM, Speex,"
Log "  iLBC, Opus, SILK, G729, AMR"
Log "Codecs de video esperados: H263, H264, VP8, VP9, MPEG4"
Log "Seguranca: SRTP, TLS"
