@echo off
chcp 65001 >nul
title Local Transcriber - Inicializador Remoto
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-all-remote.ps1"
if errorlevel 1 (
    echo.
    echo Ocorreu um erro ao iniciar o Local Transcriber Remoto.
    pause
)
