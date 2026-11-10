from .base import *  # noqa: F401,F403

DEBUG = False
SECRET_KEY = "test-secret-key"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CELERY_TASK_ALWAYS_EAGER = True
PWA_CACHE_VERSION = "test"

# Serve static via finders; no collectstatic needed outside prod.
WHITENOISE_AUTOREFRESH = True
WHITENOISE_USE_FINDERS = True
