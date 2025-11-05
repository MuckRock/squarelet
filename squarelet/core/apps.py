from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.AutoField'
    name = 'squarelet.core'

    def ready(self):
        import squarelet.core.signals