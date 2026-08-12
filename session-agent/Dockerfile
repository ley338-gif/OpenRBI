# NOTE: This is the only OpenRBI component that legitimately needs access to
# the container-runtime socket. It must never share a network namespace or
# credentials with the backend/frontend, and must never be reachable from
# inside a browser sandbox (see docs/adr/0004, 0005).
FROM python:3.11-slim AS base

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app ./app

EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
