# Django
from celery import Celery
from django.apps import AppConfig, apps
from django.conf import settings

# Standard Library
import os
import ssl

if not settings.configured:
    # set the default Django settings module for the 'celery' program.
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE", "config.settings.local"
    )  # pragma: no cover


if settings.CELERY_BROKER_URL.startswith("rediss:"):
    app = Celery(
        "squarelet",
        broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
        redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    )
else:
    app = Celery("squarelet")


class CeleryAppConfig(AppConfig):
    name = "squarelet.taskapp"
    verbose_name = "Celery Config"

    def ready(self):
        # Using a string here means the worker will not have to
        # pickle the object when using Windows.
        app.config_from_object("django.conf:settings")
        installed_apps = [app_config.name for app_config in apps.get_app_configs()]
        app.autodiscover_tasks(lambda: installed_apps, force=True)


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")  # pragma: no cover
