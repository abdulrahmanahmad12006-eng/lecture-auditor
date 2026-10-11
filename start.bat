@echo off
REM Start script for Lecture Auditor
REM Creates/activates virtual environment, installs dependencies, starts the server

set VENV_DIR=.venv
if not exist "%VENV_DIR%" (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
)
call "%VENV_DIR%\Scripts\activate"
echo Installing dependencies...
pip install -e .
echo Starting server...
python lecture_auditor\app.py