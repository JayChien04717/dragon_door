FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Cloud Run uses PORT env variable (default 8080 for HTTP)
# WebSocket runs on 8765, HTTP on 8000
EXPOSE 8000 8765

CMD ["python", "server.py"]
