# Debian slim, not Alpine: psycopg[binary] and lxml ship manylinux wheels
# that won't install on musl without a build toolchain. See project_notes.md.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# No Chromium anymore — Maps moved to the Places API (New) over httpx, so the
# only OS-level need is CA certs for outbound TLS to the Google/Meta/Resend
# APIs. (psycopg[binary] + lxml bundle their own native libs via wheels.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
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
