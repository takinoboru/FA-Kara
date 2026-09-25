$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

$PythonCommand = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { $null }
if (-not $PythonCommand) {
    throw "未找到 Python。请先安装 Python 3.11 或 3.12。"
}

if ($PythonCommand -eq "py") {
    & py -3.12 -m venv .venv
} else {
    & python -m venv .venv
}

$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
& $VenvPython -m pip install -r requirements-gui.txt
& $VenvPython -c 'import nltk; nltk.download("cmudict", quiet=True)'

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "未检测到 ffmpeg。音频转码和视频压制前请安装 ffmpeg。"
}

Write-Host "安装完成。运行 .\scripts\run_gui.ps1 启动 FA-Kara Studio。"
