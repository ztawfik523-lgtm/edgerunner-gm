# Multi-stage build supporting linux/arm64 and linux/amd64
FROM node:22-slim AS ui-builder
WORKDIR /app/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ARG INSTALL_SEMANTIC=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REDKB_DB=/data/rules.sqlite \
    REDGM_CAMPAIGN_DB=/data/campaign.sqlite \
    REDGM_SETTINGS_FILE=/data/settings.json \
    REDGM_HOST=0.0.0.0 \
    REDGM_PORT=8765

WORKDIR /app

COPY requirements.txt requirements-semantic.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_SEMANTIC" = "true" ]; then pip install --no-cache-dir -r requirements-semantic.txt; fi

COPY *.py ./
COPY server/ ./server/
COPY turn_engine/ ./turn_engine/
COPY --from=ui-builder /app/ui/dist ./ui/dist

RUN useradd --create-home --shell /usr/sbin/nologin redgm \
    && mkdir -p /data /home/redgm/.cache/cyberpunk-red-gm \
    && chown -R redgm:redgm /app /data /home/redgm

USER redgm
VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"REDGM_PORT\", \"8765\")}/health', timeout=3)"]

CMD ["python", "redkb.py", "serve", "--from-settings"]
