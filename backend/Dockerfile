FROM python:3.11-slim AS base

RUN useradd --create-home --uid 10001 openrbi
WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

USER openrbi
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
