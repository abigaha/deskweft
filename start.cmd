@echo off
rem Start the deskweft helper hidden at logon. Run once; remove with uninstall.ps1.
setlocal
set "ROOT=%~dp0"
start "" /min "%ROOT%.venv\Scripts\pythonw.exe" -m deskweft.server
endlocal
