@echo off
rem Builds the Windows program folder (build\ in the source folder) without an installer, then zips it into
rem dist\pfemame_windows_v<version>.zip for release.
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

rem The release zip:  dist\pfemame_windows_v<version>.zip
python "%~dp0make_windows_zip.py"
if errorlevel 1 (
    echo.
    echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    echo ! The build worked but the zip FAILED - see the messages above !
    echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    pause
    exit /b 1
)

@echo.
@echo !!!!!!!!! Build, copy and zip are complete !!!!!!!!!
@echo.
pause