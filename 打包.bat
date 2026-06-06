@echo off
setlocal

set "PYTHON_EXE=C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "PYINSTALLER_PATH=%CD%\.packaging\pyinstaller"
set "APP_ICON=%CD%\assets\app.ico"

if exist "%PYTHON_EXE%" (
    if not exist "%PYINSTALLER_PATH%\PyInstaller\__main__.py" (
        "%PYTHON_EXE%" -m pip install --target "%PYINSTALLER_PATH%" PyInstaller
        if errorlevel 1 exit /b 1
    )
    set "PYTHONPATH=%PYINSTALLER_PATH%"
    "%PYTHON_EXE%" -m PyInstaller -F -w main.py -n NetworkTool --icon "%APP_ICON%"
) else (
    pyinstaller -F -w main.py -n NetworkTool --icon "%APP_ICON%"
)

endlocal
