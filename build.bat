@echo off
rem Rebuild ScreenPin.exe. Needs: pip install pyinstaller
cd /d "%~dp0"
echo Building ScreenPin.exe ...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ScreenPin ^
  --icon "%~dp0screenpin.ico" ^
  --version-file "%~dp0version_info.txt" ^
  --add-data "%~dp0screenpin\web;screenpin/web" ^
  --exclude-module tkinter --exclude-module unittest --exclude-module pydoc ^
  --exclude-module pdb --exclude-module doctest ^
  --distpath "%~dp0dist" --workpath "%~dp0build" --specpath "%~dp0build" ^
  main.py
if errorlevel 1 goto fail
copy /y "%~dp0dist\ScreenPin.exe" "%~dp0ScreenPin.exe" >nul
echo.
echo Done -^> ScreenPin.exe
pause
exit /b 0
:fail
echo.
echo BUILD FAILED
pause
exit /b 1
