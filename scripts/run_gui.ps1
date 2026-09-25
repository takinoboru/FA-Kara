$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "尚未安装环境，请先运行 .\scripts\setup.ps1。"
}

Set-Location $ProjectDir
& $VenvPython -m streamlit run kara_gui.py
