"""How code outside this app queues a task. Services never call .delay() directly."""
import logging
from functools import partial

from django.db import transaction

logger = logging.getLogger(__name__)


def _run(task, args):
    try:
        task.delay(*args)
    except Exception:  # noqa: BLE001  (a down broker must not break the request that already committed)
        logger.exception("Could not queue %s%r", task.name, args)


def enqueue(task, *args):
    """Queue the task once the surrounding transaction commits (immediately if there isn't one).
    Tasks only ever receive primary keys."""
    transaction.on_commit(partial(_run, task, args))
