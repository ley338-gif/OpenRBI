FROM python:3.11-slim AS base

# libmagic1: backing library for python-magic (real magic-byte file-type
# detection, Phase 13 download interception — never trust extension or
# declared Content-Type alone, docs/policies.md).
# Pulls in whatever OS security patches Debian has actually released for
# this base image since it was last pulled — some upstream CVEs still show
# up as unfixed afterward (Debian hasn't backported a patch yet), tracked
# explicitly in .trivyignore rather than silently accepted (A5).
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 openrbi
WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

RUN mkdir -p /app/data/staging && chown -R openrbi:openrbi /app/data

USER openrbi
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
