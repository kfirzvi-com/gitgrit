"""The ``#compliance`` anchor that ``standards.failing`` notifications link to,
and the ``#project-results`` Standards card.

The anchor wraps the Health card on the full page, outside anything HTMX swaps,
so a link lands even before the card has loaded; the Standards card keeps its
own id across its poll.
"""
import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestProjectResultsAnchor(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant, role="member")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(tenant.id)
        session.save()
        self.project = baker.make("app.Project", tenant=tenant)

    def test_project_page_has_the_anchor(self):
        resp = self.client.get(reverse("project_detail", args=[self.project.pk]))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'id="project-results"' in body
        assert 'id="compliance"' in body

    def test_the_anchor_wraps_the_health_card_outside_the_polls(self):
        body = self.client.get(reverse("project_detail", args=[self.project.pk])).content.decode()
        anchor = body.index('id="compliance"')
        assert anchor < body.index('id="project-history"') < body.index('id="project-results"')

        poll = self.client.get(reverse("project_results", args=[self.project.pk])).content.decode()
        assert 'id="project-results"' in poll
        assert 'id="compliance"' not in poll
