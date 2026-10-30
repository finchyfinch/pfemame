@echo off
rem Builds the Windows program folder (build\ in the source folder) without an installer.
rem Paths are relative to this file (%~dp0 = the tools folder), so it works whatever folder it is started from.
if exist "%~dp0..\build" rmdir /S /Q "%~dp0..\build"
python "%~dp0setup.py" build --verbose
if errorlevel 1 (
    echo.
    echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    echo ! Build FAILED - see the messages above !
    echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    pause
    exit /b 1
)

@echo.
@echo !!!!!!!!! Build and copy is complete !!!!!!!!!
@echo.
pause