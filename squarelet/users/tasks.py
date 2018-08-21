
# Django
from celery import task

# Local
from . import update
from .models import User


@task(name="update_muckrock_user")
def update_muckrock_user(user_pk):
    user = User.objects.get(pk=user_pk)
    update.muckrock(user)


@task(name="update_doccloud_user")
def update_doccloud_user(user_pk):
    user = User.objects.get(pk=user_pk)
    update.doccloud(user)


@task(name="update_all")
def push_update_user(user_pk):
    updaters = [update_muckrock_user]
    for updater in updaters:
        updater.delay(user_pk)
