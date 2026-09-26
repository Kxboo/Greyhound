param([string]$OutputDirectory = (Join-Path $PSScriptRoot '..\test-output\terrain-images'))
$ErrorActionPreference = 'Stop'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vsRoot = & $vswhere -latest -products * -property installationPath
Import-Module (Join-Path $vsRoot 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll')
Enter-VsDevShell -VsInstallPath $vsRoot -SkipAutomaticLocation -DevCmdArguments '-arch=x64 -host_arch=x64' | Out-Null
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$includes = @("/I$repo\src\WraithX\WraithX", "/I$repo\src\WraithXCOD\WraithXCOD",
    "/I$repo\src\External\DirectXTex\DirectXTex")
$exe = Join-Path $OutputDirectory 'terrain_image_roundtrip.exe'
$log = Join-Path $OutputDirectory 'build.log'
$sources = @((Join-Path $PSScriptRoot 'shared/native/terrain_image_roundtrip.cpp'),
    "$repo\src\WraithXCOD\WraithXCOD\exporters\CoDRawImageTranslator.cpp",
    "$repo\src\WraithXCOD\WraithXCOD\assets\CoDAssetType.cpp",
    "$repo\src\WraithXCOD\WraithXCOD\exporters\CoDXAnimReader.cpp")
# Build Greyhound Release first so this links the actual current Image implementation.
$libs = @("$repo\src\WraithXCOD\x64\Release\WraithX.lib",
    "$repo\src\External\DirectXTex\DirectXTex\Bin\Desktop_2019_Win10\x64\Release\DirectXTex.lib",
    'windowscodecs.lib', 'd3d11.lib', 'dxguid.lib', 'shlwapi.lib')
& cl.exe /nologo /std:c++17 /EHsc /O2 /Gy /MD /D_UNICODE /DUNICODE @includes "/Fo$OutputDirectory\" "/Fe$exe" @sources /link /LTCG /OPT:REF @libs *> $log
if ($LASTEXITCODE -ne 0) { Get-Content -LiteralPath $log -Tail 35; exit $LASTEXITCODE }
& $exe $OutputDirectory
exit $LASTEXITCODE
