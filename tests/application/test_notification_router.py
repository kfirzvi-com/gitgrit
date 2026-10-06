"""A typo in a kind must still reach someone, and the seeded kinds must route."""

from django.test import SimpleTestCase

from app.application.notifications.router import RULES, rule_for
from app.domain.notifications import Audience, Rule


class RuleForTests(SimpleTestCase):
    def test_known_kinds_return_their_rule(self):
        for kind in ("run.failed", "standards.failing", "graph.failed"):
            with self.subTest(kind=kind):
                self.assertIs(rule_for(kind), RULES[kind])
                self.assertEqual(rule_for(kind), Rule(Audience.team(), ("inbox",)))

    def test_unknown_kind_falls_back_to_admins_on_inbox_and_warns(self):
        with self.assertLogs("app.application.notifications.router", "WARNING"):
            rule = rule_for("nope")

        self.assertEqual(rule, Rule(Audience.admins(), ("inbox",)))
