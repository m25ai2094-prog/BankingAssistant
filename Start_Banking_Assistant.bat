@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto python
py -3 run.py --open %*
goto done
:python
python run.py --open %*
:done
pause
