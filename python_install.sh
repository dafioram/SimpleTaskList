#!/bin/bash
# Cross-platform Python package installer (Git Bash + Ubuntu)

set -e
set -u

cd "$(dirname "$0")"

PYTHON_CMD="python"
REQUIREMENTS_FILE=requirements.txt

# Detect OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "Detected Linux system."
    PYTHON_CMD="python3"
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "win32" ]]; then
    echo "Detected Windows (Git Bash)."
else
    echo "Unknown OS type: $OSTYPE"
fi

# Check if Python is installed
if ! command -v "$PYTHON_CMD" >/dev/null 2>&1; then
    echo "❌ Python not found. Please install Python manually:"
    echo "   https://www.python.org/downloads/"
    exit 1
fi

if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
    echo "❌ $REQUIREMENTS_FILE not found in $(pwd)"
    exit 1
fi

# Upgrade pip
echo "Upgrading pip..."
"$PYTHON_CMD" -m pip install --upgrade pip

echo "Installing packages from $REQUIREMENTS_FILE..."
"$PYTHON_CMD" -m pip install -r "$REQUIREMENTS_FILE"

echo
echo "Python environment setup complete."
"$PYTHON_CMD" --version
echo "Start the app with ./run.sh"
