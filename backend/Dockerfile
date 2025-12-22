FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg (includes ffprobe) for video duration validation
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all Python source files (excluding tests in production, but keeping for now)
COPY *.py ./

# Copy JSON config files (Stripe plans configuration)
COPY stripe_plans_*.json ./


EXPOSE 8000

# Use uvicorn with reload for development (ENVIRONMENT=development)
# For production, use gunicorn or uvicorn without reload
# --reload enables hot reload, --reload-dir specifies directories to watch
CMD ["sh", "-c", "if [ \"$ENVIRONMENT\" = \"development\" ]; then uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /app; else python main.py; fi"]

