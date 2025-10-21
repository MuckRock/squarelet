from django.apps import AppConfig

class HijacksConfig(AppConfig):
    name = "hijacks"

    def ready(self):
        import hijacks.signals
