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
