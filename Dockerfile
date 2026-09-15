# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS wheels
WORKDIR /build
COPY requirements.txt .
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim-bookworm
ARG APP_VERSION=dev
LABEL org.opencontainers.image.title="Pocket Ledger" \
      org.opencontainers.image.description="Private multi-profile spending and savings ledger" \
      org.opencontainers.image.source="https://github.com/mariof1/pocket-ledger" \
      org.opencontainers.image.version="${APP_VERSION}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LEDGER_INSTANCE=/data \
    LEDGER_VERSION=${APP_VERSION}
WORKDIR /app
RUN groupadd --gid 10001 ledger && \
    useradd --uid 10001 --gid 10001 --home-dir /app --no-create-home ledger && \
    install -d -m 0750 -o ledger -g ledger /app /data
COPY --from=wheels /wheels /wheels
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && \
    rm -rf /wheels
COPY --chown=ledger:ledger *.py VERSION ./
COPY --chown=ledger:ledger static ./static
USER 10001:10001
VOLUME ["/data"]
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/bootstrap', timeout=3)" || exit 1
CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "--threads=4", "app:app"]
