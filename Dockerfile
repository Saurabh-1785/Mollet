FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mollet ./mollet
COPY scripts ./scripts
ENV MOLLET_DB=/data/mollet.db
RUN mkdir -p /data
EXPOSE 8000
CMD ["sh", "-c", "uvicorn mollet.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
