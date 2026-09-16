"""Views for attaching standards to projects.

Covers the web surface of the attachment feature: the project-page picker
endpoint (GET partial / POST set), the add-project flow persisting selected
standards, the single-run endpoint rejecting unattached standards, and the
project detail page listing/scoring only attached standards.

Runs are queued, never executed here: the background job's ``defer`` is
mocked, so a passing test also proves no sandbox was started.
"""
import re
from unittest import mock

import pytest
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.domain.models import Project, StandardExecution
from tests.support import defer_patch, running_executions



def _flashes(resp):
    return [m.message for m in get_messages(resp.wsgi_request)]


# Render full pages without the manifest static storage (no collectstatic in tests).
NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


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
    return baker.make(
        "app.Project", tenant=tenant, platform_connection=connection, **kw
    )


def _standard(tenant, **kw):
    kw.setdefault("enabled", True)
    kw.setdefault("draft", False)
    return baker.make("app.Standard", tenant=tenant, **kw)


def _checkbox_is_checked(body, standard_pk):
    return re.search(
        rf'<input[^>]*value="{standard_pk}"[^>]*checked', body
    ) is not None


@pytest.mark.django_db
class TestProjectStandardsPicker(TestCase):
    def test_get_renders_picker_with_attached_checked(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        attached = _standard(tenant, name="Attached standard")
        unattached = _standard(tenant, name="Unattached standard")
        project.standards.add(attached)

        resp = self.client.get(
            reverse("project_standards", args=[project.pk]),
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Attached standard" in body
        assert "Unattached standard" in body
        assert _checkbox_is_checked(body, attached.pk)
        assert not _checkbox_is_checked(body, unattached.pk)

    def test_plain_get_redirects_to_project_page(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        resp = self.client.get(reverse("project_standards", args=[project.pk]))
        assert resp.status_code == 302
        assert resp.url == reverse("project_detail", args=[project.pk])

    def test_post_replaces_attachment_set(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        s1, s2, s3 = (_standard(tenant) for _ in range(3))
        project.standards.add(s1)

        url = reverse("project_standards", args=[project.pk])
        with defer_patch():
            resp = self.client.post(url, data={"standards": [str(s2.pk), str(s3.pk)]})
        assert resp.status_code == 302
        assert set(project.standards.all()) == {s2, s3}

        # Posting nothing detaches everything.
        resp = self.client.post(url, data={})
        assert resp.status_code == 302
        assert project.standards.count() == 0

    def test_post_ignores_standards_of_other_tenants(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        foreign = _standard(baker.make("app.Tenant"))

        resp = self.client.post(
            reverse("project_standards", args=[project.pk]),
            data={"standards": [str(foreign.pk)]},
        )
        assert resp.status_code == 302
        assert project.standards.count() == 0

    def test_project_of_other_tenant_is_not_found(self):
        _login_member(self.client)
        other_project = _project(baker.make("app.Tenant"))
        resp = self.client.get(reverse("project_standards", args=[other_project.pk]))
        assert resp.status_code == 404


@pytest.mark.django_db
class TestSingleRunRequiresAttachment(TestCase):
    def _run(self, project, standard):
        return self.client.post(
            reverse("run_project_standards", args=[project.pk]),
            data={"standard_id": str(standard.pk)},
        )

    def test_unattached_standard_is_rejected(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        standard = _standard(tenant)  # active but not attached

        with defer_patch() as configure:
            resp = self._run(project, standard)

        assert resp.status_code == 302
        assert resp.url == reverse("project_detail", args=[project.pk])
        configure.assert_not_called()
        assert not running_executions(project).exists()
        assert "Standard not found or not active." in _flashes(resp)

    def test_attached_standard_runs(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        standard = _standard(tenant)
        project.standards.add(standard)

        with defer_patch() as configure:
            resp = self._run(project, standard)

        assert resp.status_code == 302
        assert resp.url == reverse("project_detail", args=[project.pk])
        row = running_executions(project).get()
        assert row.standard_id == standard.pk
        configure.assert_called_once_with(lock=f"standards:{project.pk}")
        configure.return_value.defer.assert_called_once_with(
            project_id=str(project.pk), execution_ids=[str(row.pk)]
        )
        assert any("Queued" in m for m in _flashes(resp))


@pytest.mark.django_db
class TestAddProjectPersistsStandards(TestCase):
    def test_selected_standards_are_attached(self):
        _, tenant = _login_member(self.client)
        connection = baker.make(
            "app.PlatformConnection",
            tenant=tenant,
            platform="github",
            access_token="ghp_x",
        )
        s1 = _standard(tenant)
        _standard(tenant)  # not selected

        client = mock.Mock()
        client.get_languages.return_value = []
        client.get_topics.return_value = []
        client.create_webhook.return_value = "hook-1"
        with mock.patch(
            "app.presentation.views.project_views.get_platform_client",
            return_value=client,
        ), defer_patch() as configure:
            resp = self.client.post(
                reverse("add_project_search", args=[connection.id]),
                data={
                    "external_id": "42",
                    "name": "app",
                    "full_path": "acme/app",
                    "web_url": "https://github.com/acme/app",
                    "default_branch": "main",
                    "lifecycle": "development",
                    "standards": [str(s1.pk)],
                },
            )
        assert resp.status_code == 302
        project = Project.objects.get(tenant=tenant, external_id="42")
        assert set(project.standards.all()) == {s1}
        # Attaching at creation is a coverage change — the standard is queued.
        assert [r.standard_id for r in running_executions(project)] == [s1.pk]
        configure.assert_called_once_with(lock=f"standards:{project.pk}")

    def test_no_selection_attaches_nothing(self):
        _, tenant = _login_member(self.client)
        connection = baker.make(
            "app.PlatformConnection",
            tenant=tenant,
            platform="github",
            access_token="ghp_x",
        )
        _standard(tenant)

        client = mock.Mock()
        client.get_languages.return_value = []
        client.get_topics.return_value = []
        client.create_webhook.return_value = "hook-1"
        with mock.patch(
            "app.presentation.views.project_views.get_platform_client",
            return_value=client,
        ):
            resp = self.client.post(
                reverse("add_project_search", args=[connection.id]),
                data={
                    "external_id": "43",
                    "name": "bare",
                    "full_path": "acme/bare",
                    "web_url": "https://github.com/acme/bare",
                    "default_branch": "main",
                    "lifecycle": "development",
                },
            )
        assert resp.status_code == 302
        project = Project.objects.get(tenant=tenant, external_id="43")
        assert project.standards.count() == 0


@pytest.mark.django_db
class TestAttachTriggersRuns(TestCase):
    """Attachment is a coverage change: the newly attached, runnable delta is
    queued (job defer mocked — trigger wiring under test)."""

    def _post(self, project, standards):
        with defer_patch() as configure:
            resp = self.client.post(
                reverse("project_standards", args=[project.pk]),
                data={"standards": [str(s.pk) for s in standards]},
            )
        assert resp.status_code == 302
        self.resp = resp
        return configure

    def test_only_newly_attached_runnable_standards_run(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        already = _standard(tenant)
        new_runnable = _standard(tenant)
        new_draft = _standard(tenant, draft=True)
        project.standards.add(already)

        configure = self._post(project, [already, new_runnable, new_draft])

        assert [r.standard_id for r in running_executions(project)] == [new_runnable.pk]
        configure.assert_called_once_with(lock=f"standards:{project.pk}")
        assert any("Queued" in m for m in _flashes(self.resp))

    def test_reposting_the_same_set_runs_nothing(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        standard = _standard(tenant)
        project.standards.add(standard)

        configure = self._post(project, [standard])

        configure.assert_not_called()
        assert not running_executions(project).exists()


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestProjectDetailShowsAttachedOnly(TestCase):
    def test_lists_attached_and_filters_executions(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        attached = _standard(tenant, name="Attached standard")
        detached = _standard(tenant, name="Detached standard")
        project.standards.add(attached)
        # Explicit statuses: the model defaults to RUNNING, and in-flight rows
        # are deliberately kept out of the score.
        baker.make(
            "app.StandardExecution",
            project=project,
            standard=attached,
            score=100,
            status=StandardExecution.Status.PASSED,
        )
        baker.make(
            "app.StandardExecution",
            project=project,
            standard=detached,
            score=0,
            status=StandardExecution.Status.FAILED,
        )

        resp = self.client.get(reverse("project_detail", args=[project.pk]))
        assert resp.status_code == 200
        assert [s.pk for s in resp.context["attached_standards"]] == [attached.pk]
        # The detached standard's execution must not drag the score.
        assert resp.context["compliance_score"] == 100
        assert all(
            ex.standard_id == attached.pk
            for ex in resp.context["recent_executions"]
        )

    def test_empty_state_prompts_attachment(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        _standard(tenant)  # workspace has a standard, but none attached

        resp = self.client.get(reverse("project_detail", args=[project.pk]))
        assert resp.status_code == 200
        assert "No standards attached" in resp.content.decode()
