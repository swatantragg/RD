# Royalty platform API; the same image runs the background worker and the one-shot bootstrap (migrations, seed)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN groupadd --system --gid 10001 mrm && useradd --system --uid 10001 --gid mrm --home-dir /app --shell /usr/sbin/nologin mrm
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY mrm ./mrm
RUN mkdir -p /data/objects && chown -R mrm:mrm /data
USER mrm
ENV STORAGE_ROOT=/data/objects
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=8 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)" || exit 1
CMD ["uvicorn", "mrm.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
