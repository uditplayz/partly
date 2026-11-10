from .base import *  # noqa: F401,F403
from .base import INSTALLED_APPS, MIDDLEWARE, env

DEBUG = True
INTERNAL_IPS = ["127.0.0.1"]

try:
    import debug_toolbar  # noqa: F401
except ImportError:  # pragma: no cover
    pass
else:
    INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
    MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware", *MIDDLEWARE]

# Without Redis on the machine, run tasks inline. Set CELERY_TASK_ALWAYS_EAGER=False to use a real broker.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=True)

# Serve static via finders; no collectstatic needed outside prod.
WHITENOISE_AUTOREFRESH = True
WHITENOISE_USE_FINDERS = True
