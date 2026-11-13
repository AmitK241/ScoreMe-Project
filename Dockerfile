# Production Dockerfile for Decision Platform (Unified Backend + Frontend)
FROM python:3.11-slim

WORKDIR /app

# Prevent Python from writing .pyc files & enable unbuffered stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src ./src
COPY config ./config
COPY backend ./backend
COPY frontend ./frontend
COPY examples ./examples

# Set Python search path
ENV PYTHONPATH="/app/src:/app/backend"

# Expose default port
EXPOSE 8000

# Run uvicorn
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

