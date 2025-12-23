FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg (includes ffprobe) for video duration validation
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire app/ directory structure
COPY app/ ./app/

# Copy JSON config files (Stripe plans configuration) to app/core/assets/
# Note: These should already be in app/core/assets/ from the migration, but we copy them here for safety
# If files don't exist in build context, they won't be copied (that's fine)
COPY stripe_plans_live.json ./app/core/assets/
COPY stripe_plans_test.json ./app/core/assets/

# Copy test files (for CI/testing, not included in production)
# These are only used during test runs, not in production containers
# If files don't exist in build context, they won't be copied (that's fine)
COPY test_main.py ./
COPY test_security.py ./
COPY pytest.ini ./

EXPOSE 8000

# Use uvicorn with reload for development (ENVIRONMENT=development)
# For production, use uvicorn without reload
# --reload enables hot reload, --reload-dir specifies directories to watch
# Updated to use app.main:app instead of main:app
CMD ["sh", "-c", "if [ \"$ENVIRONMENT\" = \"development\" ]; then uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /app/app; else uvicorn app.main:app --host 0.0.0.0 --port 8000; fi"]

