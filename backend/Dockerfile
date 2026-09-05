FROM python:3.11-slim

# Install system dependencies (needed for pdfplumber/psycopg2)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv
RUN pip install uv

# Copy project files
COPY pyproject.toml .python-version ./

# Install dependencies using uv
RUN uv pip install --system -r pyproject.toml

# Copy source code
COPY src/ ./src/

# Expose port (if running a web server later)
EXPOSE 8000

# Entrypoint (placeholder for now)
CMD ["python", "-m", "backend"]
