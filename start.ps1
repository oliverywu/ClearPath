param(
    [switch]$Reset,
    [string]$Fixture = '',
    [int]$WebPort = 3000,
    [int]$ApiPort = 8000
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonCandidates = @()
foreach ($commandName in @('python', 'python3', 'py')) {
    $candidate = Get-Command $commandName -ErrorAction SilentlyContinue
    if ($candidate -and $candidate.Source -notlike '*WindowsApps*') { $pythonCandidates += $candidate.Source }
}
$pythonCandidates += Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$pythonExecutable = $null
foreach ($candidate in $pythonCandidates) {
    if (Test-Path -LiteralPath $candidate) {
        & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { $pythonExecutable = $candidate; break }
    }
}
if (-not $pythonExecutable) { throw 'Install Python 3.11 or later, then run .\start.ps1 again.' }
$launcherArgs = @('start.py', '--web-port', "$WebPort", '--api-port', "$ApiPort")
if ($Reset) { $launcherArgs += '--reset' }
if ($Fixture) { $launcherArgs += @('--fixture', $Fixture) }
& $pythonExecutable @launcherArgs
exit $LASTEXITCODE

