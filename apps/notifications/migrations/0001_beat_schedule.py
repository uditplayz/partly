from django.db import migrations

from apps.notifications.beat import SCHEDULE


def install(apps, schema_editor):
    Crontab = apps.get_model("django_celery_beat", "CrontabSchedule")
    Periodic = apps.get_model("django_celery_beat", "PeriodicTask")
    for name, task, minute, hour in SCHEDULE:
        crontab, _ = Crontab.objects.get_or_create(
            minute=minute, hour=hour, day_of_week="*", day_of_month="*", month_of_year="*", timezone="Asia/Kolkata"
        )
        Periodic.objects.update_or_create(name=name, defaults={"task": task, "crontab": crontab, "enabled": True})


def remove(apps, schema_editor):
    apps.get_model("django_celery_beat", "PeriodicTask").objects.filter(name__in=[row[0] for row in SCHEDULE]).delete()


class Migration(migrations.Migration):
    dependencies = [("django_celery_beat", "0019_alter_periodictasks_options")]
    operations = [migrations.RunPython(install, remove)]
