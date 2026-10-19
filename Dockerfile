FROM python:3.11.2-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.lock ./
RUN python -m pip install --no-cache-dir --requirement requirements.lock

RUN groupadd --system app && useradd --system --gid app --create-home app
COPY --chown=app:app . .
USER app

# Run the complete public suite against the synthetic fixtures included in the image.
CMD ["python", "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
