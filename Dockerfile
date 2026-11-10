FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

# Exact versions with hashes, wheels only: nothing runs a package setup script during the build.
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes --only-binary :all: -r requirements.lock

COPY . .

# collectstatic needs settings to load; these values exist only for this one build step.
RUN SECRET_KEY=build-only ALLOWED_HOSTS=build REDIS_URL=redis://build:6379/0 \
    DATABASE_URL=postgres://build@build/build PAYMENT_PROVIDER=razorpay \
    python manage.py collectstatic --noinput

RUN useradd --system --uid 10001 --no-create-home partly && chmod +x deploy/entrypoint.sh
USER partly

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python", "deploy/healthcheck.py"]
ENTRYPOINT ["deploy/entrypoint.sh"]
CMD ["web"]
