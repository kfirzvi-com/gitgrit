"""Updating an installed marketplace standard saves a new version, which queues
the standard to re-run on every project it is attached to — and the flash must
say so, like every other save path."""
import pytest
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from tests.support import defer_patch, running_executions


def _login_member(client):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant")
    baker.make("app.Membership", user=user, tenant=tenant, role="owner")
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


@pytest.mark.django_db
class TestMarketplaceUpdateQueuesRuns(TestCase):
    def test_flash_reports_the_queued_runs(self):
        _, tenant = _login_member(self.client)
        mp = baker.make(
            "app.MarketplaceStandard", slug="readme", name="README", code="def evaluate(p): pass", version=2
        )
        standard = baker.make(
            "app.Standard",
            tenant=tenant,
            source_marketplace_standard=mp,
            source_version=1,
            enabled=True,
            draft=False,
        )
        project = baker.make("app.Project", tenant=tenant)
        project.standards.add(standard)

        with defer_patch():
            resp = self.client.post(reverse("update_marketplace_standard", args=[mp.slug]))

        assert resp.status_code == 302
        flashes = [m.message for m in get_messages(resp.wsgi_request)]
        assert any("Queued 1 standard on 1 project" in m for m in flashes), flashes
        assert running_executions(project).count() == 1
