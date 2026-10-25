FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OPENMED_OFFLINE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MODEL_ROOT=/models \
    HF_HOME=/tmp/huggingface XDG_CACHE_HOME=/tmp/cache
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin clinical-ai
COPY . /app/
USER 10001:10001
EXPOSE 8081
HEALTHCHECK --interval=20s --timeout=4s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/readyz',timeout=3)"]
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1", "--no-access-log", "--log-level", "warning", "--no-proxy-headers"]
