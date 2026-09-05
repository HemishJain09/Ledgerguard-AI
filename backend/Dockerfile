FROM python:3.13-slim

# Install system dependencies (needed for pdfplumber & psycopg2)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv package manager
RUN pip install uv

# Copy project definition files
COPY pyproject.toml uv.lock .python-version ./

# Install all dependencies from lock file for reproducible builds
RUN uv sync --frozen

# Copy source code and config
COPY src/ ./src/
COPY server.py config.yaml ./

# Expose FastAPI port
EXPOSE 8000

# Start the FastAPI server
CMD ["uv", "run", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
