FROM python:3.11-slim

WORKDIR /app

# Set PYTHONPATH so 'app' folder is treated as a package
ENV PYTHONPATH=/app
# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 1. Copy requirements first to leverage Docker cache
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copy the app code
# Your tree shows: backend/app/
# We want this to end up as /app/app/ inside the container
COPY backend/app/ ./app/

# 3. Copy support files from the backend folder
COPY backend/tests/ ./tests/
COPY backend/pytest.ini ./
COPY backend/alembic.ini ./
COPY backend/migrations/ ./migrations/

# 4. Copy the scripts folder from the PROJECT ROOT
# This matches your tree: ./scripts/ (containing backup-db.sh, setup_stripe.py, etc.)
COPY scripts/ ./scripts/

EXPOSE 8000

# Refined CMD: Using the module path app.main:app
CMD ["sh", "-c", "if [ \"$ENVIRONMENT\" = \"development\" ]; then \
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /app/app; \
    else \
    uvicorn app.main:app --host 0.0.0.0 --port 8000; \
    fi"]