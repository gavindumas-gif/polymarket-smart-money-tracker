FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations
COPY fixtures ./fixtures
COPY config.example.yaml ./

RUN python -m pip install --no-cache-dir -e .

CMD ["python", "-m", "polymarket_tracker.cli", "--config", "config.example.yaml", "dry-run"]

