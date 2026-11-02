@echo off
rem Double-click to stop BASIC_OS and its background ComfyUI (frees the GPU for other apps).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_basic_os.ps1" %*
