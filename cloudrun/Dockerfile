FROM python:3.11-slim

# Install system dependencies including FFmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
COPY cloudrun/requirements.txt cloudrun_requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r cloudrun_requirements.txt

# Copy all project files
COPY . .

# Expose port
EXPOSE 8080

# Run the server
CMD ["python", "cloudrun/server.py"]
