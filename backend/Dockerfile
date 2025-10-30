FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY client_secrets.json /app/client_secrets.json

# Verify file was copied
RUN ls -la /app/client_secrets.json && cat /app/client_secrets.json | head -1

EXPOSE 8000

CMD ["python", "main.py"]

