from .base import *  # noqa: F401,F403
from django.core.exceptions import ImproperlyConfigured

from .base import PAYMENT_PROVIDER, STORAGES, env

DEBUG = False
SECRET_KEY = env("SECRET_KEY")  # required in prod, no default

STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# The mock provider lets a host publish without paying. Never allow it in production by accident.
if PAYMENT_PROVIDER == "mock" and not env.bool("ALLOW_MOCK_PAYMENTS", default=False):
    raise ImproperlyConfigured("Set PAYMENT_PROVIDER=razorpay in production (or ALLOW_MOCK_PAYMENTS=True for a demo).")

# --- Email and Celery in production -----------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_TIMEOUT = 15  # a hung SMTP server must not pin a worker forever

# A real broker is required. No silent fallback to localhost, no inline task execution.
CELERY_BROKER_URL = env("REDIS_URL")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_ALWAYS_EAGER = False
