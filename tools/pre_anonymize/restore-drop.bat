@echo off
chcp 65001 >nul
rem Восстановление реальных данных в черновике от ассистента.
rem Перетащите на этот ярлык ДВА файла разом: черновик (.docx/.md/.txt)
rem и соответствующий *.mapping.json из workflow\_anonymizer\_ready. Порядок не важен.
setlocal enabledelayedexpansion
cd /d "%~dp0..\.."
title pre-anonymize restore

set "DRAFT="
set "MAPPING="

for %%F in (%*) do (
    if /I "%%~xF"==".json" (
        set "MAPPING=%%~fF"
    ) else (
        set "DRAFT=%%~fF"
    )
)

if "%DRAFT%"=="" goto usage
if "%MAPPING%"=="" goto usage

echo Черновик: %DRAFT%
echo Mapping:  %MAPPING%
echo.

python tools\pre_anonymize\prepare.py restore "%DRAFT%" --mapping "%MAPPING%"
goto end

:usage
echo ОШИБКА: нужно перетащить на этот ярлык ДВА файла сразу —
echo   1) черновик от ассистента (.docx / .md / .txt)
echo   2) файл *.mapping.json из workflow\_anonymizer\_ready
echo Выделите оба файла в проводнике (Ctrl+клик) и перетащите вместе.

:end
echo.
pause
