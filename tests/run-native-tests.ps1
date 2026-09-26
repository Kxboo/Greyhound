param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\test-output\native-tests'),
    [string]$TestPattern = '*'
)
$ErrorActionPreference = 'Stop'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vsRoot = & $vswhere -latest -products * -property installationPath
Import-Module (Join-Path $vsRoot 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll')
Enter-VsDevShell -VsInstallPath $vsRoot -SkipAutomaticLocation -DevCmdArguments '-arch=x64 -host_arch=x64' | Out-Null
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$includeRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\src\WraithX\WraithX'))
$appIncludeRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\src\WraithXCOD\WraithXCOD'))
$testRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd([char[]]'\/') + [IO.Path]::DirectorySeparatorChar
$tests = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*_test.cpp' -File -Recurse |
    Sort-Object FullName |
    Where-Object { $_.FullName.Substring($testRoot.Length).Replace('\', '/') -like $TestPattern })
if (-not $tests.Count) { throw "No native tests matched '$TestPattern'." }
$results = @()
foreach ($test in $tests) {
    $relativePath = $test.FullName.Substring($testRoot.Length).Replace('\', '/')
    $outputPath = Join-Path $OutputDirectory $relativePath
    New-Item -ItemType Directory -Path (Split-Path $outputPath) -Force | Out-Null
    $exe = [IO.Path]::ChangeExtension($outputPath, '.exe')
    $obj = [IO.Path]::ChangeExtension($outputPath, '.obj')
    $log = [IO.Path]::ChangeExtension($outputPath, '.log')
    & cl.exe /nologo /std:c++17 /EHsc /O2 /DNOMINMAX "/I$appIncludeRoot" "/I$includeRoot" "/Fo$obj" "/Fe$exe" $test.FullName *> $log
    $compiled = $LASTEXITCODE -eq 0
    $passed = $false
    if ($compiled) {
        if ($test.BaseName -eq 'model_batch_resume_test') {
            $fixture = Join-Path $OutputDirectory ('resume-fixture-' + [guid]::NewGuid().ToString('N'))
            & $exe --self-test $fixture *>> $log
        } else { & $exe *>> $log }
        $passed = $LASTEXITCODE -eq 0
    }
    $results += [pscustomobject]@{ test=$relativePath; compiled=$compiled; passed=$passed; log=$log }
    Write-Output "${relativePath}: compiled=$compiled passed=$passed"
}
$results | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'results.json') -Encoding utf8
if ($results.Where({-not $_.passed}).Count) { exit 1 }
