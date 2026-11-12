# Backend image: used for BOTH the API and the worker (different start command, see
# docker-compose.yml). Build context is BD_BACKEND/. No secrets here: configuration
# arrives as environment variables at run time.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install dev tools (pytest, ruff) too. Local compose sets true; production builds leave it false.
ARG INSTALL_DEV=false

WORKDIR /srv

RUN useradd --create-home --uid 10001 appuser

COPY . .
RUN if [ "$INSTALL_DEV" = "true" ]; then pip install -e ".[dev]"; else pip install -e .; fi \
    && chown -R appuser:appuser /srv

USER appuser
EXPOSE 8000

# Default: API. The worker service overrides this command.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
