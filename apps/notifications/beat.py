"""The periodic jobs. A data migration copies these into django-celery-beat's tables, where
they can be paused or retimed in the Django admin. Re-running the migration step is safe
(update_or_create by name), but admin edits to a job listed here are overwritten when a new
migration touching it ships."""

# (name, dotted task path, minute, hour) in Asia/Kolkata. "*/15" style values are cron fields.
SCHEDULE = [
    ("partly: send event reminders", "apps.notifications.tasks.dispatch_upcoming_event_reminders", "*/15", "*"),
    ("partly: mark finished events completed", "apps.notifications.tasks.mark_completed_events", "*/15", "*"),
    ("partly: expire unpaid listing orders", "apps.notifications.tasks.expire_stale_payment_orders", "*/10", "*"),
    ("partly: recompute all trust scores", "apps.notifications.tasks.recompute_all_trust_scores", "30", "3"),
]
