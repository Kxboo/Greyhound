param([string]$OutputDirectory = (Join-Path $PSScriptRoot '..\test-output\radiant'))
$ErrorActionPreference = 'Stop'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vsRoot = & $vswhere -latest -products * -property installationPath
Import-Module (Join-Path $vsRoot 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll')
Enter-VsDevShell -VsInstallPath $vsRoot -SkipAutomaticLocation -DevCmdArguments '-arch=x64 -host_arch=x64' | Out-Null
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$exe = Join-Path $OutputDirectory 'radiant_export_result_test.exe'
$log = Join-Path $OutputDirectory 'result-test-build.log'
& cl.exe /nologo /std:c++17 /EHsc /O2 /MD "/I$repo\src\WraithXCOD\WraithXCOD" "/I$repo\src\WraithX\WraithX" "/Fo$OutputDirectory\" "/Fe$exe" (Join-Path $PSScriptRoot 'shared/native/radiant_export_result_test.cpp') *> $log
if ($LASTEXITCODE -ne 0) { Get-Content -LiteralPath $log -Tail 35; exit $LASTEXITCODE }
& $exe
exit $LASTEXITCODE
