"""Production must not print emails (and the tokens in them) to the log."""
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from app.checks import console_email_backend, log_console_email_warning

CONSOLE_EMAIL_BACKEND = settings.EMAIL_BACKENDS["console"]
SMTP = settings.EMAIL_BACKENDS["smtp"]


class TestConsoleEmailBackendCheck(SimpleTestCase):
    @override_settings(DEBUG=False, EMAIL_BACKEND=CONSOLE_EMAIL_BACKEND)
    def test_warns_in_production_with_the_console_backend(self):
        results = console_email_backend(None)
        assert [r.id for r in results] == ["gitgrit.W002"]
        assert "tokens" in results[0].msg
        assert "EMAIL_HOST" in results[0].hint
        real = "|".join(name for name in settings.EMAIL_BACKENDS if name != "console")
        assert f"GITGRIT_EMAIL_BACKEND={real}" in results[0].hint

    @override_settings(DEBUG=True, EMAIL_BACKEND=CONSOLE_EMAIL_BACKEND)
    def test_quiet_in_debug(self):
        assert console_email_backend(None) == []

    @override_settings(DEBUG=False, EMAIL_BACKEND=SMTP)
    def test_quiet_with_smtp(self):
        assert console_email_backend(None) == []

    def test_the_check_is_registered(self):
        from django.core.checks.registry import registry

        assert console_email_backend in registry.registered_checks

    @override_settings(DEBUG=False, EMAIL_BACKEND=CONSOLE_EMAIL_BACKEND)
    def test_startup_log_says_it_in_production(self):
        for argv in (
            ["manage.py", "runserver"],
            ["/usr/local/bin/gunicorn", "gitgrit.wsgi"],
            ["manage.py", "procrastinate", "worker"],
        ):
            with self.subTest(argv=argv), self.assertLogs("app.checks", "WARNING") as logs:
                log_console_email_warning(argv)
            assert "tokens" in logs.output[0]

    @override_settings(DEBUG=False, EMAIL_BACKEND=CONSOLE_EMAIL_BACKEND)
    def test_startup_log_is_quiet_for_other_commands(self):
        for command in ("collectstatic", "check", "migrate", "shell", "test"):
            with self.subTest(command=command), self.assertNoLogs("app.checks", "WARNING"):
                log_console_email_warning(["manage.py", command])

    @override_settings(DEBUG=False, EMAIL_BACKEND=SMTP)
    def test_startup_log_is_quiet_with_smtp(self):
        with self.assertNoLogs("app.checks", "WARNING"):
            log_console_email_warning(["manage.py", "runserver"])
