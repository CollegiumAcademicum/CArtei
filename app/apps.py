from django.apps import AppConfig


class CarteiAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app"

    def ready(self):
        from app import signals  # noqa: F401  (registers login/logout receivers)
