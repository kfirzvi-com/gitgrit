"""StackMap: dependants above what they depend on."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from app.application.project_health_counts import ProjectHealthCounts
from app.presentation.stack_map import StackMap


def _stack(pk, name):
    return SimpleNamespace(pk=pk, name=name)


COUNTS = ProjectHealthCounts(failed=0, needs_attention=1, healthy=1)


class StackMapTests(SimpleTestCase):
    def setUp(self):
        self.web, self.api, self.platform = _stack("w", "Web"), _stack("a", "API"), _stack("p", "Platform")
        self.rows = [(s, COUNTS) for s in (self.web, self.api, self.platform)]

    def test_dependants_sit_above_what_they_depend_on(self):
        stack_map = StackMap(self.rows, {("w", "a"): set(), ("a", "p"): set(), ("w", "p"): set()})

        y = {node.stack.name: node.y for node in stack_map.nodes}
        self.assertLess(y["Web"], y["API"])
        self.assertLess(y["API"], y["Platform"])
        self.assertEqual(len(stack_map.edges), 3)

    def test_a_cycle_does_not_hang_and_keeps_only_downward_edges(self):
        stack_map = StackMap(self.rows, {("w", "a"): set(), ("a", "w"): set()})

        self.assertEqual(len(stack_map.nodes), 3)
        self.assertEqual(len(stack_map.edges), 1)

    def test_unrelated_stacks_share_one_row(self):
        stack_map = StackMap(self.rows, {})

        self.assertEqual(len({node.y for node in stack_map.nodes}), 1)
        self.assertEqual(stack_map.edges, [])
