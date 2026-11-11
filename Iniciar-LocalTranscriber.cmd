@echo off
chcp 65001 >nul
title Local Transcriber (Local)
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-local-transcriber.ps1" -OpenBrowser
if errorlevel 1 (
    echo.
    echo Ocorreu um erro ao iniciar o Local Transcriber.
    pause
)
