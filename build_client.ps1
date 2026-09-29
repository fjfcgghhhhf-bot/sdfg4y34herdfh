$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
$oldPath = $env:PATH
try {
    if (-not (Test-Path -LiteralPath '.build-venv\Scripts\python.exe')) {
        py -3 -m venv .build-venv
        if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать окружение Python.' }
    }
    $python = Join-Path $PSScriptRoot '.build-venv\Scripts\python.exe'
    & $python -m pip install -r client-requirements.txt pyinstaller
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить зависимости.' }
    $env:PATH = (Split-Path -Parent $python) + ';' + $PSScriptRoot + '\.build-venv\Lib\site-packages\PyQt6\Qt6\bin;' + $env:SystemRoot + '\System32;' + $env:SystemRoot
    & $python -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin --name DebuffRemoteClientV3 --paths desktop --add-data 'desktop/assets;assets' --add-data 'LICENSE-chess.txt;.' client.py
    if ($LASTEXITCODE -ne 0) { throw 'Сборка EXE завершилась ошибкой.' }
    Write-Host 'Готово: dist\DebuffRemoteClientV3.exe'
} finally {
    $env:PATH = $oldPath
    Pop-Location
}
