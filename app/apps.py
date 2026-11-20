from django.apps import AppConfig


class AppConfig(AppConfig):
    name = 'app'

    def ready(self):
        import app.checks  # noqa: F401  — register deployment-time system checks
        import app.signals  # noqa: F401
        import app.tasks  # noqa: F401  — register the Procrastinate task

        from app.application import subscribers

        subscribers.register()

        # The worker process only. Web and other management commands are not
        # wrapped. See app.worker_heartbeat.install_worker_heartbeat.
        from app.worker_heartbeat import install_worker_heartbeat

        install_worker_heartbeat()
