FROM python:3.12-slim

RUN apt-get update && apt-get install -y potrace && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD gunicorn app:app --timeout 120 --workers 1 --bind 0.0.0.0:10000
