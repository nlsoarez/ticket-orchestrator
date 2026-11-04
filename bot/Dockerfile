FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /data \
    && chown 65532:65532 /data
COPY __init__.py runtime.py server.py workspace.py purchase_planning.py monitor.py monitor_scheduler.py ./bot/
EXPOSE 8000
USER 65532:65532
CMD ["uvicorn", "bot.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
