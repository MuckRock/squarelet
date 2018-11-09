# Django
from celery import current_app
from django.db import transaction


class SyncableMixin:
    """A model which will sync itself to client sites"""

    sync_actions = ()

    def _get_sync_args(self):
        """Arguments to identify the model in the sync task"""
        return (self.pk,)

    def save(self, *args, **kwargs):
        """Push saves to client sites"""
        with transaction.atomic():
            action = "create" if self._state.adding else "update"
            super().save(*args, **kwargs)
            if action in self.sync_actions:
                transaction.on_commit(
                    lambda: current_app.send_task(
                        "sync.sync",
                        (self.__class__.__name__, action, self._get_sync_args()),
                    )
                )

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            super().delete(*args, **kwargs)
            if "delete" in self.sync_actions:
                transaction.on_commit(
                    lambda: current_app.send_task(
                        "sync.sync",
                        (self.__class__.__name__, "delete", self._get_sync_args()),
                    )
                )
