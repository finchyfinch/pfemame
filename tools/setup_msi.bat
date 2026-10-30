@echo off
rem Builds the Windows installer:  dist\pfeMAME-<version>-win64.msi  (in the source folder).
rem Paths are relative to this file (%~dp0 = the tools folder), so it works whatever folder it is started from.
rem (It used to remove tools\build instead of the real build folder.)
if exist "%~dp0..\build" rmdir /S /Q "%~dp0..\build"
if exist "%~dp0..\build_msi_temp" rmdir /S /Q "%~dp0..\build_msi_temp"
python "%~dp0setup.py" bdist_msi
if errorlevel 1 (
    echo.
    echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    echo ! MSI build FAILED - see the messages above !
    echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    pause
    exit /b 1
)

@echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
@echo ! Build and copy is complete !
@echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
pause