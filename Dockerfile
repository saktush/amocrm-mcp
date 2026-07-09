FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY amocrm_mcp ./amocrm_mcp

RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 1000 --user-group --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown -R app:app /app /data

USER app

ENV AMO_TRANSPORT=http \
    AMO_PORT=8000 \
    AMO_TOKEN_FILE=/data/.amo_tokens.json

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1', int(os.environ.get('AMO_PORT', 8000)))); s.close()"

CMD ["python", "-m", "amocrm_mcp"]
