param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    [ValidateSet("x64", "Win32")]
    [string]$Platform = "x64",
    [switch]$BuildOnly
)

$ErrorActionPreference = "Stop"

$vswherePath = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $vswherePath)) {
    throw "Visual Studio Installer (vswhere.exe) was not found."
}
$visualStudioPath = & $vswherePath -latest -products * -property installationPath
if (-not $visualStudioPath) { throw "Visual Studio 2022 was not found." }

$mfcHeader = Get-ChildItem (Join-Path $visualStudioPath "VC\Tools\MSVC") -Directory |
    ForEach-Object { Join-Path $_.FullName "atlmfc\include\afxwin.h" } |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
if (-not $mfcHeader) {
    throw "Install 'C++ MFC for latest v143 build tools (x86 & x64)'."
}

$msbuildPath = Join-Path $visualStudioPath "MSBuild\Current\Bin\MSBuild.exe"
$solutionPath = Join-Path $PSScriptRoot "src\WraithXCOD\WraithXCOD.sln"
& $msbuildPath $solutionPath /m:1 /t:Build "/p:Configuration=$Configuration" "/p:Platform=$Platform" /p:PlatformToolset=v143 /v:minimal
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($BuildOnly) { return }

$builtExe = Join-Path $PSScriptRoot "src\WraithXCOD\$Platform\$Configuration\Greyhound.exe"
if (-not (Test-Path -LiteralPath $builtExe)) { throw "Built executable not found: $builtExe" }

$runtimeRoots = @(
    (Join-Path $PSScriptRoot "bin"),
    (Join-Path $PSScriptRoot "bin\cli")
)
foreach ($runtimeRoot in $runtimeRoots) {
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    $target = if ($runtimeRoot.EndsWith("\cli")) {
        Join-Path $runtimeRoot "Greyhound-cli.exe"
    } else {
        Join-Path $runtimeRoot "Greyhound.exe"
    }
    Copy-Item -LiteralPath $builtExe -Destination $target -Force

    $runtimeTools = Join-Path $runtimeRoot "tools"
    if (Test-Path -LiteralPath $runtimeTools) {
        Remove-Item -LiteralPath $runtimeTools -Recurse -Force
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "tools") -Destination $runtimeTools -Recurse -Force
}

$pythonCandidates = @()
if ($env:SUPERTERRAIN_PYTHON) { $pythonCandidates += $env:SUPERTERRAIN_PYTHON }
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCommand) { $pythonCandidates += $pythonCommand.Source }
$pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($pyLauncher) { $pythonCandidates += $pyLauncher.Source }

$capturePython = $null
foreach ($candidate in ($pythonCandidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $capturePython = $candidate; break }
}
if ($capturePython) {
    foreach ($runtimeRoot in $runtimeRoots) {
        Set-Content -LiteralPath (Join-Path $runtimeRoot "terrain-python.txt") -Value $capturePython -Encoding ascii
    }
    "staged source-only Greyhound runtimes with Python $capturePython"
} else {
    Write-Warning "No Python 3.10+ runtime found. Set SUPERTERRAIN_PYTHON before exporting terrain."
}
