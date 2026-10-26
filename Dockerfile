FROM python:3.12-slim-bookworm

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Użytkownik bez uprawnień roota; dane w wolumenie /app/data.
RUN useradd --system --uid 10001 --home-dir /app appuser \
 && mkdir /app/data && chown appuser /app/data
USER appuser

ENV DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1
VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

# --no-access-log: nie zapisujemy żadnych adresów IP.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
