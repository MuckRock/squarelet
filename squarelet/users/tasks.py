# Django
from celery import shared_task

# Squarelet
from squarelet.users.mail import PermissionsDigest


@shared_task
def permission_digest():
    PermissionsDigest().send()
