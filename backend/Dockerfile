FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all Python source files (excluding tests in production, but keeping for now)
COPY *.py ./

# Copy scripts directory (utility scripts like setup_stripe.py)
COPY scripts/ ./scripts/

# Note: client_secrets.json is mounted as a volume in docker-compose.yml
# This allows it to be gitignored and provided at runtime
# .dockerignore excludes: __pycache__, venv/, uploads/, etc.

EXPOSE 8000

CMD ["python", "main.py"]

