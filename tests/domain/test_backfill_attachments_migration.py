"""The 0029 backfill attaches every existing standard to every tenant project.

Live workspaces must keep behaving exactly as before attachments existed, so
the data migration cross-joins projects and standards per tenant — including
disabled and draft standards, so one later re-enabled or published keeps
running workspace-wide. The migration's RunPython functions only use
``apps.get_model`` on models whose current state matches the migration state,
so they are invoked here directly with the live app registry.
"""
from importlib import import_module

import pytest
from django.apps import apps
from django.test import TestCase
from model_bakery import baker

from app.domain.models import ProjectStandard

_migration = import_module(
    "app.migrations.0029_backfill_project_standard_attachments"
)


@pytest.mark.django_db
class TestBackfillAttachments(TestCase):
    def test_attaches_every_tenant_standard_to_every_tenant_project(self):
        tenant = baker.make("app.Tenant")
        projects = baker.make("app.Project", tenant=tenant, _quantity=2)
        standards = baker.make("app.Standard", tenant=tenant, _quantity=3)

        _migration.attach_all_tenant_standards(apps, None)

        for project in projects:
            assert set(project.standards.all()) == set(standards)

    def test_disabled_and_draft_standards_are_attached_too(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        disabled = baker.make("app.Standard", tenant=tenant, enabled=False)
        draft = baker.make("app.Standard", tenant=tenant, draft=True)

        _migration.attach_all_tenant_standards(apps, None)

        assert set(project.standards.all()) == {disabled, draft}

    def test_does_not_attach_across_tenants(self):
        project = baker.make("app.Project")
        baker.make("app.Standard")  # gets its own tenant, foreign to project's

        _migration.attach_all_tenant_standards(apps, None)

        assert project.standards.count() == 0

    def test_rerun_is_idempotent(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        baker.make("app.Standard", tenant=tenant)

        _migration.attach_all_tenant_standards(apps, None)
        _migration.attach_all_tenant_standards(apps, None)

        assert ProjectStandard.objects.filter(project=project).count() == 1

    def test_reverse_detaches_everything(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        standard = baker.make("app.Standard", tenant=tenant)
        project.standards.add(standard)

        _migration.detach_all(apps, None)

        assert ProjectStandard.objects.count() == 0
