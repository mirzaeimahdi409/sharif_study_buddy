# Use an official Python runtime as a parent image
# Change base image to invalidate cache
FROM python:3.12.4-slim-bookworm

# Add a build argument to invalidate the cache
ARG CACHE_BUSTER=1

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install uv - the fast Python package installer
RUN apt-get update && apt-get install -y curl && \
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    apt-get remove -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Add uv to the PATH
ENV PATH="/root/.local/bin:$PATH"

# Set work directory
WORKDIR /app

# Invalidate cache to force re-copying requirements.txt
COPY requirements.txt /app/
RUN uv pip install --system --no-cache -r requirements.txt

# Copy project files
COPY . /app/

# Ensure entrypoint script is executable (explicit permissions)
RUN chmod 755 /app/entrypoint.sh && \
    ls -la /app/entrypoint.sh

# Expose port for the app
EXPOSE 8014

ENTRYPOINT ["/bin/sh", "/app/entrypoint.sh"]
