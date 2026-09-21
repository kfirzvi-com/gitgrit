"""Stack page views: renaming a stack and managing its components via the picker.

Covers the edit endpoint (rename + description, empty-name rejection, tenant
isolation) and the components endpoint (GET partial with members pre-checked /
POST replacing the membership set, firing add/remove events).
"""
import re
from unittest import mock

import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import Component, Project
from app.tasks import infer_project_dependencies


def _login_member(client):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant")
    baker.make("app.Membership", user=user, tenant=tenant, role="owner")
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


def _project(tenant, **kw):
    connection = kw.pop(
        "connection",
        baker.make("app.PlatformConnection", tenant=tenant, platform="github"),
    )
    kw.setdefault("tags", [])
    kw.setdefault("languages", [])
    return baker.make(
        "app.Project", tenant=tenant, platform_connection=connection, **kw
    )


def _root(project):
    return project.root_component


def _members(stack):
    return set(Component.objects.filter(stacks=stack))


# Render full pages without the manifest static storage (no collectstatic in tests).
NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


def _checkbox_is_checked(body, pk):
    return re.search(rf'<input[^>]*value="{pk}"[^>]*checked', body) is not None


@pytest.mark.django_db
class TestEditStack(TestCase):
    def test_post_renames_stack(self):
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant, name="Old", description="")

        resp = self.client.post(
            reverse("edit_stack", args=[stack.pk]),
            data={"name": "  New name ", "description": "About it"},
        )
        assert resp.status_code == 302
        assert resp.url == reverse("stack_detail", args=[stack.pk])
        stack.refresh_from_db()
        assert stack.name == "New name"
        assert stack.description == "About it"

    def test_empty_name_is_rejected(self):
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant, name="Keep me")

        resp = self.client.post(
            reverse("edit_stack", args=[stack.pk]), data={"name": "   "}
        )
        assert resp.status_code == 302
        stack.refresh_from_db()
        assert stack.name == "Keep me"

    def test_stack_of_other_tenant_is_not_found(self):
        _login_member(self.client)
        foreign = baker.make("app.Stack", tenant=baker.make("app.Tenant"), name="X")
        resp = self.client.post(
            reverse("edit_stack", args=[foreign.pk]), data={"name": "Hijacked"}
        )
        assert resp.status_code == 404
        foreign.refresh_from_db()
        assert foreign.name == "X"


@pytest.mark.django_db
class TestStackComponentsPicker(TestCase):
    def test_get_renders_picker_with_members_checked(self):
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant)
        member = _project(tenant, name="Member project")
        other = _project(tenant, name="Other project")
        _project(baker.make("app.Tenant"), name="Foreign project")
        _root(member).stacks.add(stack)

        resp = self.client.get(
            reverse("stack_components", args=[stack.pk]),
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Member project" in body
        assert "Other project" in body
        assert "Foreign project" not in body
        assert _checkbox_is_checked(body, _root(member).pk)
        assert not _checkbox_is_checked(body, _root(other).pk)

    def test_get_lists_every_component_of_a_monorepo(self):
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant)
        mono = _project(tenant, name="mono", full_path="org/mono")
        gateway = baker.make(
            "app.Component", tenant=tenant, project=mono, path="apps/api-gateway", name="api-gateway"
        )

        resp = self.client.get(
            reverse("stack_components", args=[stack.pk]),
            headers={"HX-Request": "true"},
        )
        body = resp.content.decode()
        assert "api-gateway" in body
        assert "apps/api-gateway" in body
        assert f'value="{gateway.pk}"' in body
        assert f'value="{_root(mono).pk}"' in body

    def test_plain_get_redirects_to_stack_page(self):
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant)
        resp = self.client.get(reverse("stack_components", args=[stack.pk]))
        assert resp.status_code == 302
        assert resp.url == reverse("stack_detail", args=[stack.pk])

    def test_post_replaces_membership_and_publishes_events(self):
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant)
        p1, p2, p3 = (_project(tenant) for _ in range(3))
        _root(p1).stacks.add(stack)

        url = reverse("stack_components", args=[stack.pk])
        with mock.patch("app.application.stack_service.publish") as publish:
            resp = self.client.post(
                url, data={"components": [str(_root(p2).pk), str(_root(p3).pk)]}
            )
        assert resp.status_code == 302
        assert _members(stack) == {_root(p2), _root(p3)}
        assert set(Project.objects.filter(components__stacks=stack)) == {p2, p3}
        events = [c.args[0] for c in publish.call_args_list]
        assert sorted(type(e).__name__ for e in events) == [
            "ComponentAddedToStack",
            "ComponentAddedToStack",
            "ComponentRemovedFromStack",
        ]
        # The graph subscriber refreshes per repository, so every event names its project.
        assert {e.project_id for e in events} == {str(p1.pk), str(p2.pk), str(p3.pk)}

        # Posting nothing empties the stack.
        resp = self.client.post(url, data={})
        assert resp.status_code == 302
        assert not _members(stack)

    def test_post_adds_several_projects_when_a_deps_job_is_already_queued(self):
        """Regression: the add-to-stack subscriber queues a dependency refresh
        per project. When one is already queued, Procrastinate's unique
        queueing_lock rejects the insert; without a savepoint that aborts the
        whole membership transaction and the next project's write fails with
        "current transaction is aborted" (InternalError 500)."""
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant)
        p1, p2 = (_project(tenant) for _ in range(2))
        # What ProjectCreated leaves behind until a graph worker picks it up.
        infer_project_dependencies.configure(
            lock=f"project:{p1.pk}", queueing_lock=f"deps:{p1.pk}"
        ).defer(project_id=str(p1.pk))

        url = reverse("stack_components", args=[stack.pk])
        resp = self.client.post(
            url, data={"components": [str(_root(p1).pk), str(_root(p2).pk)]}
        )

        assert resp.status_code == 302
        assert _members(stack) == {_root(p1), _root(p2)}

    def test_post_ignores_projects_of_other_tenants(self):
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant)
        foreign = _project(baker.make("app.Tenant"))

        resp = self.client.post(
            reverse("stack_components", args=[stack.pk]),
            data={"components": [str(_root(foreign).pk)]},
        )
        assert resp.status_code == 302
        assert not _members(stack)

    def test_stack_of_other_tenant_is_not_found(self):
        _login_member(self.client)
        foreign = baker.make("app.Stack", tenant=baker.make("app.Tenant"))
        resp = self.client.get(
            reverse("stack_components", args=[foreign.pk]),
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 404


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestStackDetailPage(TestCase):
    def test_page_offers_edit_and_manage_components(self):
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant, name="My stack")
        _root(_project(tenant, name="In stack")).stacks.add(stack)

        resp = self.client.get(reverse("stack_detail", args=[stack.pk]))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert reverse("edit_stack", args=[stack.pk]) in body
        assert reverse("stack_components", args=[stack.pk]) in body
        assert "Manage components" in body
        assert "In stack" in body

    def test_remove_component_endpoint(self):
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant)
        root = _root(_project(tenant, name="Gone soon"))
        root.stacks.add(stack)

        resp = self.client.post(
            reverse("remove_component_from_stack", args=[stack.pk, root.pk])
        )
        assert resp.status_code == 302
        assert not _members(stack)
