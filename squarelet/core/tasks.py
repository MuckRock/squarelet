# Django
from celery import shared_task
from django.core.management import call_command


@shared_task
def db_cleanup():
    """Call some management commands to clean up the database"""
    call_command("clearsessions", verbosity=2)
    call_command("deleterevisions", days=730, verbosity=2)
