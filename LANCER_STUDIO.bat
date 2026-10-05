@echo off
rem Ouvre le Studio du parseur Lua dans le navigateur.
rem Un dossier ou un fichier .lua depose sur ce fichier s'ouvre directement.
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHON="

rem 1. Les emplacements habituels de Python, du plus recent au plus ancien.
rem    Chaque candidat est essaye pour de bon : une installation deplacee ou
rem    supprimee est ignoree au lieu de bloquer le lancement.
for %%V in (314 313 312 311 310) do (
    if not defined PYTHON call :essayer_fichier "%ProgramFiles%\Python%%V\python.exe"
    if not defined PYTHON call :essayer_fichier "%LocalAppData%\Programs\Python\Python%%V\python.exe"
    if not defined PYTHON call :essayer_fichier "%SystemDrive%\Python%%V\python.exe"
)

rem 2. Le lanceur py, version par version, puis les commandes du PATH.
for %%V in (3.14 3.13 3.12 3.11 3.10) do (
    if not defined PYTHON call :essayer_commande py -%%V
)
if not defined PYTHON call :essayer_commande python
if not defined PYTHON call :essayer_commande python3
if not defined PYTHON call :essayer_commande py -3

if not defined PYTHON (
    echo.
    echo Aucun Python 3.10 ou plus recent n'a ete trouve sur cet ordinateur.
    echo Installez-le depuis https://www.python.org/downloads/ puis relancez ce fichier.
    echo.
    pause
    exit /b 1
)

echo Python utilise : %PYTHON%
%PYTHON% -m lua_parser_pro --gui %*
if errorlevel 1 pause
exit /b

:essayer_fichier
if not exist "%~1" exit /b 1
"%~1" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 exit /b 1
set PYTHON="%~1"
exit /b 0

:essayer_commande
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 exit /b 1
set PYTHON=%*
exit /b 0
