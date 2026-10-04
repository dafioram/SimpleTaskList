#!/bin/bash
# Run TaskApp directly (no Docker, no systemd).
#   Linux:            gunicorn with gunicorn.conf.py (same as Docker and the service)
#   Windows Git Bash: Flask's built-in server (gunicorn doesn't run on Windows)
# Run ./python_install.sh first to install the requirements.
#
# Settings come from .env if it exists (PORT, API_BACKUP_KEY, ...).
# FLASK_DEBUG=1 ./run.sh turns on the debugger and auto-reload (Windows/dev only;
# it then listens on 127.0.0.1 unless HOST is set).

set -e
set -u

cd "$(dirname "$0")"

if [[ -f .env ]]; then
    set -a
    # Strip Windows line endings so values don't end in \r
    source <(sed 's/\r$//' .env)
    set +a
fi

PYTHON_CMD="python"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    PYTHON_CMD="python3"
fi

if ! command -v "$PYTHON_CMD" >/dev/null 2>&1; then
    echo "❌ $PYTHON_CMD not found. Run ./python_install.sh first."
    exit 1
fi

if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    echo "Windows detected: starting Flask's built-in server on port ${PORT:-5000}..."
    exec "$PYTHON_CMD" run.py
else
    echo "Starting gunicorn on port ${PORT:-5000}..."
    exec "$PYTHON_CMD" -m gunicorn -c gunicorn.conf.py
fi
