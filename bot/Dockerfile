FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY __init__.py runtime.py server.py ./bot/
EXPOSE 8000
USER 65532:65532
CMD ["uvicorn", "bot.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
