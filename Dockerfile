FROM python:3.11-slim

# Set environment variables to improve Python performance in Docker
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# tzdata lets the TZ variable work, so "due today" and "done" dates use your local time
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# Unprivileged user the app runs as (see docker_entrypoint.py)
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home-dir /app --no-create-home app

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files (.dockerignore keeps .env, data/ and other local files out)
COPY . .

# The app listens on 5000 inside the container; docker-compose maps it to PORT on the host
ENV PORT=5000
EXPOSE 5000

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=4).status == 200 else 1)"

# Starts as root only long enough to fix ./data ownership, then runs as 'app'
ENTRYPOINT ["python", "/app/docker_entrypoint.py"]
CMD ["gunicorn", "-c", "gunicorn.conf.py"]
