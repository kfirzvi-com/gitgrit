"""Stack page views: renaming a stack and managing its projects via the picker.

Covers the edit endpoint (rename + description, empty-name rejection, tenant
isolation) and the projects endpoint (GET partial with members pre-checked /
POST replacing the membership set, firing add/remove events).
"""
import re
from unittest import mock

import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import Project


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
class TestStackProjectsPicker(TestCase):
    def test_get_renders_picker_with_members_checked(self):
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant)
        member = _project(tenant, name="Member project")
        other = _project(tenant, name="Other project")
        _project(baker.make("app.Tenant"), name="Foreign project")
        stack.projects.add(member)

        resp = self.client.get(
            reverse("stack_projects", args=[stack.pk]),
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Member project" in body
        assert "Other project" in body
        assert "Foreign project" not in body
        assert _checkbox_is_checked(body, member.pk)
        assert not _checkbox_is_checked(body, other.pk)

    def test_plain_get_redirects_to_stack_page(self):
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant)
        resp = self.client.get(reverse("stack_projects", args=[stack.pk]))
        assert resp.status_code == 302
        assert resp.url == reverse("stack_detail", args=[stack.pk])

    def test_post_replaces_membership_and_publishes_events(self):
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant)
        p1, p2, p3 = (_project(tenant) for _ in range(3))
        stack.projects.add(p1)

        url = reverse("stack_projects", args=[stack.pk])
        with mock.patch("app.application.stack_service.publish") as publish:
            resp = self.client.post(url, data={"projects": [str(p2.pk), str(p3.pk)]})
        assert resp.status_code == 302
        assert set(Project.objects.filter(stacks=stack)) == {p2, p3}
        event_names = sorted(type(c.args[0]).__name__ for c in publish.call_args_list)
        assert event_names == [
            "ProjectAddedToStack",
            "ProjectAddedToStack",
            "ProjectRemovedFromStack",
        ]

        # Posting nothing empties the stack.
        resp = self.client.post(url, data={})
        assert resp.status_code == 302
        assert Project.objects.filter(stacks=stack).count() == 0

    def test_post_ignores_projects_of_other_tenants(self):
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant)
        foreign = _project(baker.make("app.Tenant"))

        resp = self.client.post(
            reverse("stack_projects", args=[stack.pk]),
            data={"projects": [str(foreign.pk)]},
        )
        assert resp.status_code == 302
        assert Project.objects.filter(stacks=stack).count() == 0

    def test_stack_of_other_tenant_is_not_found(self):
        _login_member(self.client)
        foreign = baker.make("app.Stack", tenant=baker.make("app.Tenant"))
        resp = self.client.get(
            reverse("stack_projects", args=[foreign.pk]),
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 404


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestStackDetailPage(TestCase):
    def test_page_offers_edit_and_manage_projects(self):
        _, tenant = _login_member(self.client)
        stack = baker.make("app.Stack", tenant=tenant, name="My stack")
        stack.projects.add(_project(tenant, name="In stack"))

        resp = self.client.get(reverse("stack_detail", args=[stack.pk]))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert reverse("edit_stack", args=[stack.pk]) in body
        assert reverse("stack_projects", args=[stack.pk]) in body
        assert "Manage projects" in body
        assert "In stack" in body
