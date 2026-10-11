#!/bin/bash
# Start script for Lecture Auditor
# Creates/activates virtual environment, installs dependencies, starts the script

VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
echo "Installing dependencies..."
pip install -e .
echo "Starting server..."
python lecture_auditor/app.py