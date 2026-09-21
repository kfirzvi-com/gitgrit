"""The Component invariant: a project is a repository, its components are the
deployable units inside it, and there is always at least the root one."""
from django.db import IntegrityError, transaction
from django.test import TestCase
from model_bakery import baker

from app.domain.models import Component, Stack


def _project(**kw):
    tenant = kw.pop("tenant", None) or baker.make("app.Tenant")
    conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
    return baker.make("app.Project", tenant=tenant, platform_connection=conn, **kw)


class ComponentInvariantTests(TestCase):
    def test_creating_a_project_creates_its_root_component(self):
        project = _project(name="web", full_path="org/web")

        root = project.root_component
        self.assertIsNotNone(root)
        self.assertEqual(root.path, "")
        self.assertEqual(root.name, "web")
        self.assertEqual(root.tenant_id, project.tenant_id)
        self.assertTrue(root.is_root)
        self.assertEqual(root.ref, "org/web")
        self.assertEqual(project.components.count(), 1)
        self.assertFalse(project.is_monorepo)

    def test_saving_an_existing_project_adds_no_component(self):
        project = _project()
        project.name = "renamed"
        project.save()
        self.assertEqual(project.components.count(), 1)

    def test_component_paths_are_unique_per_project(self):
        project = _project()
        baker.make("app.Component", tenant=project.tenant, project=project, path="apps/x", name="x")
        with self.assertRaises(IntegrityError), transaction.atomic():
            baker.make("app.Component", tenant=project.tenant, project=project, path="apps/x", name="dup")

    def test_sub_component_ref_and_monorepo_flag(self):
        project = _project(full_path="org/mono")
        gateway = baker.make(
            "app.Component", tenant=project.tenant, project=project, path="apps/api-gateway", name="api-gateway"
        )
        self.assertEqual(gateway.ref, "org/mono#apps/api-gateway")
        self.assertFalse(gateway.is_root)
        self.assertTrue(project.is_monorepo)

    def test_project_stacks_is_the_union_of_its_components_stacks(self):
        project = _project()
        s1 = baker.make("app.Stack", tenant=project.tenant, name="A")
        s2 = baker.make("app.Stack", tenant=project.tenant, name="B")
        sub = baker.make("app.Component", tenant=project.tenant, project=project, path="svc", name="svc")
        project.root_component.stacks.add(s1)
        sub.stacks.add(s1, s2)

        self.assertEqual(set(project.stacks), {s1, s2})
        self.assertEqual(set(s1.projects), {project})
        self.assertEqual(Stack.objects.filter(components__project=project).distinct().count(), 2)

    def test_deleting_a_project_cascades_to_components(self):
        project = _project()
        baker.make("app.Component", tenant=project.tenant, project=project, path="svc", name="svc")
        project.delete()
        self.assertEqual(Component.objects.count(), 0)
