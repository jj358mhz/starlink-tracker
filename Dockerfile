FROM python:3.11-slim

WORKDIR /app

# System deps for numpy/sgp4 wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY main.py .
COPY static/ ./static/

# Data dir for TLE + ephemeris cache (mounted as volume)
RUN mkdir -p /data
WORKDIR /data

# Ephemeris and TLE will land here at first startup
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "--app-dir", "/app", "main:app", "--host", "0.0.0.0", "--port", "8000"]
