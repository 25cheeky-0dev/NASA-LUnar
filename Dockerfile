FROM node:22-bookworm-slim AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_API_BASE_URL=""
RUN npm run build
FROM python:3.13-slim
WORKDIR /wispr
COPY backend/ /wispr/backend/
COPY docs/evidence/unified/real_v3_two_cells.json /wispr/docs/evidence/unified/real_v3_two_cells.json
RUN pip install --no-cache-dir ./backend
COPY --from=ui /ui/dist /wispr/frontend/dist
ENV WISPR_STATIC_DIR=/wispr/frontend/dist
ENV PORT=8080
WORKDIR /wispr/backend
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
