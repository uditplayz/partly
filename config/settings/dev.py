from .base import *  # noqa: F401,F403
from .base import INSTALLED_APPS, MIDDLEWARE

DEBUG = True
INTERNAL_IPS = ["127.0.0.1"]

try:
    import debug_toolbar  # noqa: F401
except ImportError:  # pragma: no cover
    pass
else:
    INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
    MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware", *MIDDLEWARE]

# Serve static via finders; no collectstatic needed outside prod.
WHITENOISE_AUTOREFRESH = True
WHITENOISE_USE_FINDERS = True
