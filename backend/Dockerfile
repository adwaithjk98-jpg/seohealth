# Debian slim, not Alpine: psycopg[binary] and lxml ship manylinux wheels
# that won't install on musl without a build toolchain. See project_notes.md.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CHROME_BINARY=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Chromium + chromedriver from Debian's apt repo (matched pair, no version
# skew). Selenium 4.6+'s built-in driver manager picks them up automatically,
# so no CHROME_BINARY / CHROMEDRIVER_PATH overrides are needed at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        fonts-liberation \
        libnss3 \
        libxss1 \
        libasound2 \
        libgbm1 \
        libgtk-3-0 \
        libxkbcommon0 \
        libdrm2 \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash app

WORKDIR /app
RUN chown app:app /app

# Install Python deps as a separate, cache-friendly layer.
COPY --chown=app:app requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# App code (filtered by .dockerignore).
COPY --chown=app:app . /app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
