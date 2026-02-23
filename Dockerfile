FROM python:3.11-slim

WORKDIR /app

# Install system deps for asyncpg
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir -e "."

# Copy source
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .

CMD ["python", "-m", "src.main"]
