# Stage 1: builder — cài dependencies vào một prefix riêng
FROM python:3.11-slim AS builder
WORKDIR /build
# requirements trước source: sửa code không làm cài lại dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: runtime — chỉ copy kết quả, chạy bằng user non-root
FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN useradd --create-home --uid 10001 appuser
COPY --from=builder /install /usr/local
COPY app/ ./app/
COPY utils/ ./utils/
USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT','8000'), timeout=3)"

# exec: uvicorn thành PID 1 nên nhận được SIGTERM khi `docker stop`
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --timeout-graceful-shutdown 8"]
