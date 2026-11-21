# ==============================================================================
# Windows Launcher (PowerShell)
# ==============================================================================

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$PythonBin = "python"
if (Test-Path "$ScriptDir\.venv\Scripts\python.exe") {
    $PythonBin = "$ScriptDir\.venv\Scripts\python.exe"
} elseif (Test-Path "$ScriptDir\venv\Scripts\python.exe") {
    $PythonBin = "$ScriptDir\venv\Scripts\python.exe"
}

$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

& $PythonBin "$ScriptDir\main.py" @args
