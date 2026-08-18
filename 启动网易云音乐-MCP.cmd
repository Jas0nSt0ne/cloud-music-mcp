@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m cloud_music_mcp.visible_client
) else (
    py -m cloud_music_mcp.visible_client
)

if errorlevel 1 pause
