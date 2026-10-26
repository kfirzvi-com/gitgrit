from django.apps import AppConfig


class AppConfig(AppConfig):
    name = 'app'

    def ready(self):
        import app.checks  # register deployment-time system checks
        import app.signals  # noqa: F401
        import app.tasks  # noqa: F401  — register the Procrastinate task

        from app.application import subscribers

        subscribers.register()

        app.checks.log_console_email_warning()
