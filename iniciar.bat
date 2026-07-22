@echo off
cd /d "%~dp0"
python png_a_webp.py
if errorlevel 1 pause
