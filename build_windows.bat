@echo off
setlocal enabledelayedexpansion

:: ── instax-scanner Windows build script ──────────────────────────────────────
:: Produces:  dist\instax-scanner.exe
:: Requires:  Python 3.8+ on PATH

set VENV=build_win_env
set SRC=src\instax_gui_win.py
set ENGINE=src\instax_extract.py
set DIST=dist
set NAME=instax-scanner

echo.
echo ══════════════════════════════════════════════
echo   instax-scanner  ^|  Windows build
echo ══════════════════════════════════════════════
echo.

:: ── 1. Check Python ──────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found on PATH. Install Python 3.8+ and try again.
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo [INFO] Using %%v

:: ── 2. Create / reuse virtualenv ─────────────────────────────────────────────
if not exist "%VENV%\Scripts\activate.bat" (
    echo [INFO] Creating virtualenv in %VENV%\ ...
    python -m venv "%VENV%"
    if errorlevel 1 ( echo [ERROR] venv creation failed. & exit /b 1 )
) else (
    echo [INFO] Reusing existing virtualenv in %VENV%\
)

call "%VENV%\Scripts\activate.bat"

:: ── 3. Install / upgrade dependencies ────────────────────────────────────────
echo [INFO] Installing dependencies...
pip install --quiet --upgrade pip
pip install --quiet opencv-python numpy pyinstaller
if errorlevel 1 ( echo [ERROR] pip install failed. & exit /b 1 )

:: ── 4. Run PyInstaller ───────────────────────────────────────────────────────
echo [INFO] Running PyInstaller...

:: Clean previous build artefacts
if exist "build\%NAME%" rmdir /s /q "build\%NAME%"
if exist "%DIST%\%NAME%.exe" del /q "%DIST%\%NAME%.exe"

pyinstaller ^
    --onefile ^
    --windowed ^
    --name "%NAME%" ^
    --add-data "%CD%\%ENGINE%;." ^
    --distpath "%DIST%" ^
    --workpath "build" ^
    --specpath "build" ^
    --noconfirm ^
    "%SRC%"

if errorlevel 1 (
    echo [ERROR] PyInstaller failed.
    call "%VENV%\Scripts\deactivate.bat" 2>nul
    exit /b 1
)

call "%VENV%\Scripts\deactivate.bat" 2>nul

:: ── 5. Done ──────────────────────────────────────────────────────────────────
echo.
echo ══════════════════════════════════════════════
echo   Build complete:  %DIST%\%NAME%.exe
echo ══════════════════════════════════════════════
echo.
echo Run with:  %DIST%\%NAME%.exe
echo.

endlocal
