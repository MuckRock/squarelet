from django.apps import AppConfig

class HijacksConfig(AppConfig):
    name = "squarelet.hijacks"

    def ready(self):
        import squarelet.hijacks.signals