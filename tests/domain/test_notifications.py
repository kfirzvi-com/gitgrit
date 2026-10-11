import subprocess
import sys
from unittest import TestCase

from app.domain.notifications import plain_reason


class PlainReasonTests(TestCase):
    def test_known_causes_read_as_plain_language(self):
        cases = {
            "litellm.BadRequestError: Your credit balance is too low": "The AI provider account is out of credit.",
            "AuthenticationError: invalid x-api-key": "The AI provider rejected the API key.",
            "401 Bad credentials": "GitHub or GitLab refused GitGrit's access token.",
            "HTTPError: 403 Forbidden": "GitGrit is not allowed to read this repository.",
            "RuntimeError: GitHub API error 404 for https://api.github.com/repos/acme/repo/git/trees/feature%2Fx":
                "The branch or repository no longer exists, or GitGrit can't see it.",
            "429 rate limit exceeded": "The provider asked GitGrit to slow down. It tries again on the next push.",
            "Timed out after 240s waiting for the model": "It took too long and was stopped.",
        }
        for error, reason in cases.items():
            with self.subTest(error=error):
                self.assertEqual(plain_reason(error), reason)

    def test_unknown_errors_have_no_reason(self):
        self.assertIsNone(plain_reason("FileNotFoundError: [Errno 2] No such file: '/policy.py'"))
        self.assertIsNone(plain_reason("KeyError: 'languages'"))
        self.assertIsNone(plain_reason(""))
        self.assertIsNone(plain_reason(None))


class PurityTests(TestCase):
    def test_vocabulary_and_rules_do_not_load_django(self):
        for module in ("app.domain.notifications", "app.domain.notifications.notification_rules"):
            with self.subTest(module=module):
                code = f"import sys, {module}; sys.exit(1 if 'django' in sys.modules else 0)"
                self.assertEqual(subprocess.run([sys.executable, "-c", code]).returncode, 0)
