@echo off
setlocal
cd /d "%~dp0\..\.."
title legal-copilot unified watcher
python -m tools.watch.cli --daemon
endlocal
