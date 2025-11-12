FROM python:3.11-slim

# ADDED: Update system packages to patch known vulnerabilities
RUN apt-get update && apt-get install -y libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirement.txt .

RUN pip install --no-cache-dir -r requirement.txt

# Copy model files and scripts
COPY yolov8n.pt .
COPY knifegun1.pt .
COPY object.py .
COPY object1.py .

CMD ["python", "object.py"]