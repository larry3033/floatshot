# Build a single-file FloatShot.exe into dist\.
#
#   pip install pyinstaller
#   powershell -ExecutionPolicy Bypass -File build.ps1
#
# --windowed = no console window (the app is tray + windows only).
# config.json is NOT bundled: the app writes one next to the exe on first run,
# which is what makes the folder portable.

$ErrorActionPreference = "Stop"

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name FloatShot `
    --distpath dist `
    --workpath build `
    --specpath . `
    main.py

Write-Host ""
Write-Host "Done: dist\FloatShot.exe"
