# Windows one-command start for Cleared for Takeoff:  .\start.ps1   (or double-click start.cmd)
# Passes any arguments through, e.g. .\start.ps1 --reset   or   .\start.ps1 --check
$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot
$python = Get-Command py -ErrorAction SilentlyContinue
if ($python) { & py -3 start.py @args; exit $LASTEXITCODE }
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { Write-Error 'Python 3.11+ is required: https://www.python.org/downloads/'; exit 1 }
& python start.py @args
exit $LASTEXITCODE
