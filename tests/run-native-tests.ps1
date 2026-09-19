param([string]$OutputDirectory = (Join-Path $PSScriptRoot '..\test-output\native-tests'))
$ErrorActionPreference = 'Stop'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vsRoot = & $vswhere -latest -products * -property installationPath
Import-Module (Join-Path $vsRoot 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll')
Enter-VsDevShell -VsInstallPath $vsRoot -SkipAutomaticLocation -DevCmdArguments '-arch=x64 -host_arch=x64' | Out-Null
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$includeRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\src\WraithX\WraithX'))
$results = @()
foreach ($test in (Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*_test.cpp')) {
    $exe = Join-Path $OutputDirectory ($test.BaseName + '.exe')
    $obj = Join-Path $OutputDirectory ($test.BaseName + '.obj')
    $log = Join-Path $OutputDirectory ($test.BaseName + '.log')
    & cl.exe /nologo /std:c++17 /EHsc /O2 /DNOMINMAX "/I$includeRoot" "/Fo$obj" "/Fe$exe" $test.FullName *> $log
    $compiled = $LASTEXITCODE -eq 0
    $passed = $false
    if ($compiled) {
        if ($test.BaseName -eq 'model_batch_resume_test') {
            $fixture = Join-Path $OutputDirectory ('resume-fixture-' + [guid]::NewGuid().ToString('N'))
            & $exe --self-test $fixture *>> $log
        } else { & $exe *>> $log }
        $passed = $LASTEXITCODE -eq 0
    }
    $results += [pscustomobject]@{ test=$test.Name; compiled=$compiled; passed=$passed; log=$log }
    Write-Output "$($test.Name): compiled=$compiled passed=$passed"
}
$results | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'results.json') -Encoding utf8
if ($results.Where({-not $_.passed}).Count) { exit 1 }
