FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Note: client_secrets.json is mounted as a volume in docker-compose.yml
# This allows it to be gitignored and provided at runtime

EXPOSE 8000

CMD ["python", "main.py"]

