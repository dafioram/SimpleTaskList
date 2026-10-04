"""Flask's built-in server, for Windows and quick testing.

Linux (Docker, systemd, run.sh) uses gunicorn via gunicorn.conf.py instead.
Set FLASK_DEBUG=1 for the debugger and auto-reload; it then listens on
127.0.0.1 only (unless HOST is set), because the debugger can run code.
"""
import os

from main import app

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', '0').lower() in ('1', 'true', 'yes')
    host = os.environ.get('HOST') or ('127.0.0.1' if debug else '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    app.run(host=host, port=port, debug=debug)
