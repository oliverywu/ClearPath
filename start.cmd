@echo off
rem Windows one-command start for Cleared for Takeoff (wraps start.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
