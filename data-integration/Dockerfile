# Stateless crawl runner image.
# Production runs on GitHub Actions; this image is for local/CI reproduction.
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && playwright install --with-deps chromium

ENTRYPOINT ["ticket-ingest"]
CMD ["crawl", "--help"]
