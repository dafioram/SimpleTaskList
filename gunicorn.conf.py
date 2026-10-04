# Gunicorn settings shared by every Linux run method:
#   Docker  ->  CMD in Dockerfile
#   systemd ->  ARGS in config.env
#   shell   ->  ./run.sh
# All three run:  gunicorn -c gunicorn.conf.py
#
# Defaults suit a Raspberry Pi: one worker process with a few threads. SQLite
# allows only one writer at a time, so more processes would mostly add memory use.
# Override with environment variables if you need to.
import os

_here = os.path.dirname(os.path.abspath(__file__))

wsgi_app = 'main:app'
chdir = _here

bind = f"{os.environ.get('HOST', '0.0.0.0')}:{os.environ.get('PORT', '5000')}"
workers = int(os.environ.get('WEB_WORKERS', '1'))
threads = int(os.environ.get('WEB_THREADS', '4'))
worker_class = 'gthread'
timeout = 60
graceful_timeout = 15

# Heartbeat files in RAM instead of on the SD card / container layer.
if os.path.isdir('/dev/shm'):
    worker_tmp_dir = '/dev/shm'

# Errors go to stderr (journald / docker logs). Request logging is off by default
# to spare the Pi's SD card; set ACCESS_LOG=1 to turn it on.
errorlog = '-'
accesslog = '-' if os.environ.get('ACCESS_LOG', '0').lower() in ('1', 'true', 'yes') else None
loglevel = os.environ.get('LOG_LEVEL', 'info')

