import dataclasses
import subprocess
import sys
from unittest import TestCase

from app.domain.notifications import Audience, Notice, Severity


class AudienceTests(TestCase):
    def test_team(self):
        self.assertEqual(Audience.team().roles, ("owner", "admin", "member"))
        self.assertEqual(Audience.team().user_ids, ())

    def test_admins(self):
        self.assertEqual(Audience.admins().roles, ("owner", "admin"))

    def test_users(self):
        audience = Audience.users("a", "b")
        self.assertEqual(audience.user_ids, ("a", "b"))
        self.assertEqual(audience.roles, ())


class NoticeTests(TestCase):
    def _notice(self):
        return Notice(
            kind="k", tenant_id="t", severity=Severity.INFO, title="T", body="B", url="/"
        )

    def test_is_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self._notice().title = "x"

    def test_defaults(self):
        notice = self._notice()
        self.assertEqual(notice.context, {})
        self.assertIsNone(notice.dedupe_key)
        self.assertEqual(notice.mentioned_user_ids, ())


class PurityTests(TestCase):
    def test_import_does_not_load_django(self):
        code = (
            "import sys, app.domain.notifications;"
            "sys.exit(1 if 'django' in sys.modules else 0)"
        )
        self.assertEqual(subprocess.run([sys.executable, "-c", code]).returncode, 0)
