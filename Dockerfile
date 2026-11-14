FROM node:22-bookworm-slim AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_API_BASE_URL=""
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /wispr
COPY backend/ ./backend/
COPY docs/evidence/unified/real_v3_two_cells.json ./docs/evidence/unified/real_v3_two_cells.json
RUN pip install --no-cache-dir uv && uv sync --project backend --frozen --extra cloud --no-dev \
    && useradd --uid 10001 --create-home wispr \
    && mkdir -p /wispr/backend/data && chown -R wispr:wispr /wispr/backend/data
COPY --from=ui /ui/dist /wispr/frontend/dist
ENV WISPR_STATIC_DIR=/wispr/frontend/dist PATH="/wispr/backend/.venv/bin:$PATH"
WORKDIR /wispr/backend
USER wispr
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8080')+'/health')"
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --limit-concurrency 12 --timeout-keep-alive 5"]
