"""Which components a re-run keeps, creates and removes, and how stack
memberships carry over when a repository's shape changes."""
from django.test import SimpleTestCase

from app.domain.architecture.reconcile import inherited_memberships, plan_components


class PlanComponentsTests(SimpleTestCase):
    def test_root_only_rerun_keeps_everything(self):
        plan = plan_components([""], [""])
        self.assertEqual((plan.keep, plan.create, plan.remove), (("",), (), ()))
        self.assertFalse(plan.shape_changed)

    def test_root_becomes_monorepo(self):
        plan = plan_components([""], ["apps/a", "services/b"])
        self.assertEqual(plan.create, ("apps/a", "services/b"))
        self.assertEqual(plan.remove, ("",))
        self.assertTrue(plan.shape_changed)

    def test_partial_overlap(self):
        plan = plan_components(["apps/a", "services/b"], ["apps/a", "services/c"])
        self.assertEqual((plan.keep, plan.create, plan.remove), (("apps/a",), ("services/c",), ("services/b",)))


class InheritedMembershipsTests(SimpleTestCase):
    def test_removed_components_stacks_flow_to_created_ones(self):
        plan = plan_components([""], ["apps/a", "services/b"])
        out = inherited_memberships(plan, {"": {"storefront"}})
        self.assertEqual(out, {"apps/a": {"storefront"}, "services/b": {"storefront"}})

    def test_union_of_all_removed(self):
        plan = plan_components(["x", "y"], ["z"])
        out = inherited_memberships(plan, {"x": {"s1"}, "y": {"s2"}})
        self.assertEqual(out, {"z": {"s1", "s2"}})

    def test_no_inheritance_when_only_adding(self):
        plan = plan_components(["apps/a"], ["apps/a", "services/b"])
        self.assertEqual(inherited_memberships(plan, {"apps/a": {"s1"}}), {})

    def test_no_inheritance_when_only_removing_or_nothing_to_inherit(self):
        self.assertEqual(inherited_memberships(plan_components(["a", "b"], ["a"]), {"b": {"s"}}), {})
        self.assertEqual(inherited_memberships(plan_components([""], ["a"]), {}), {})
