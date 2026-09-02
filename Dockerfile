FROM python:3.11-slim

WORKDIR /app

# Ensure output is sent straight to terminal/logs
ENV PYTHONUNBUFFERED=1

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose Fly.io default internal port
EXPOSE 8080

# Run with gunicorn on 0.0.0.0:8080
CMD ["gunicorn", "dashboard:app", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120"]
