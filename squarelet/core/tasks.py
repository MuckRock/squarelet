# Django
from celery.schedules import crontab
from celery.task import periodic_task
from django.core.management import call_command


@periodic_task(
    run_every=crontab(day_of_week="sun", hour=1, minute=0),
    name="squarelet.core.tasks.db_cleanup",
)
def db_cleanup():
    """Call some management commands to clean up the database"""
    call_command("clearsessions", verbosity=2)
    call_command("deleterevisions", days=730, verbosity=2)
