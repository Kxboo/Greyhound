$ErrorActionPreference = 'Stop'
$terrainVs = & "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -property installationPath
Import-Module (Join-Path $terrainVs 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll')
Enter-VsDevShell -VsInstallPath $terrainVs -SkipAutomaticLocation -DevCmdArguments '-arch=x64 -host_arch=x64' | Out-Null
$terrainRepo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
$terrainInclude = Join-Path $terrainRepo 'src\WraithX\WraithX'
& cl.exe /nologo /std:c++17 /EHsc /O2 /DNOMINMAX "/I$terrainInclude" "/Fo$PSScriptRoot\run_composition.obj" "/Fe$PSScriptRoot\run_composition.exe" "$PSScriptRoot\run_composition.cpp" d3d12.lib dxgi.lib
if ($LASTEXITCODE -ne 0) { throw 'Terrain shader runner build failed' }
