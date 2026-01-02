FROM python:3.11-slim

WORKDIR /app

# Set PYTHONPATH so app module can be imported
ENV PYTHONPATH=/app

# Install ffmpeg (includes ffprobe) for video duration validation
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire app/ directory structure
# This includes app/core/assets/ with stripe_plans JSON files
COPY app/ ./app/

# Copy test directory and test files (for CI/testing, not included in production)
# These are only used during test runs, not in production containers
COPY tests/ ./tests/
COPY pytest.ini ./

EXPOSE 8000

# Use uvicorn with reload for development (ENVIRONMENT=development)
# For production, use uvicorn without reload
# --reload enables hot reload, --reload-dir specifies directories to watch
# Updated to use app.main:app instead of main:app
CMD ["sh", "-c", "if [ \"$ENVIRONMENT\" = \"development\" ]; then uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /app/app; else uvicorn app.main:app --host 0.0.0.0 --port 8000; fi"]

