# syntax=docker/dockerfile:1
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home clinical
RUN mkdir -p /var/lib/tof-clinical/utility && chown clinical:clinical /var/lib/tof-clinical/utility
COPY --chown=clinical:clinical backend/ /app/
COPY --from=frontend --chown=clinical:clinical /build/dist /app/frontend/dist
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=20s --timeout=4s --start-period=20s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=3)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
