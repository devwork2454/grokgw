FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml .
COPY grokgw/__init__.py grokgw/
RUN pip install --no-cache-dir --target /deps \
    fastapi>=0.115 uvicorn[standard]>=0.30 pydantic>=2.5

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash grokgw
COPY --from=builder /deps /usr/local/lib/python3.12/site-packages/
COPY grokgw/ /app/grokgw/
COPY pyproject.toml /app/
WORKDIR /app
RUN pip install --no-deps -e . && chown -R grokgw:grokgw /app
USER grokgw
EXPOSE 8787
ENV GROKGW_HOST=0.0.0.0 \
    GROKGW_BACKEND=proxy \
    GROKGW_AUTH_PATH=/auth/auth.json \
    PYTHONUNBUFFERED=1
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://127.0.0.1:8787/healthz || exit 1
ENTRYPOINT ["python", "-m", "grokgw"]
