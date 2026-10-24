from django.apps import AppConfig


class EditorConfig(AppConfig):
    name = 'editor'

    def ready(self):
        # Connect the honeypot receiver that writes failed /admin/ attempts to the
        # 'admin.honeypot' logger.
        from .signals import handlers  # noqa: F401
