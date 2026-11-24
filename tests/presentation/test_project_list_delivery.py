"""The Projects list's delivery columns: what each project runs, its deploy
tier and how many pull requests are open, sortable and groupable."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.domain.delivery import DeploymentStrategy
from app.models import DeliverySettings, Deployment, Platform


class ProjectListDeliveryTests(TestCase):
    def setUp(self):
        user = baker.make("app.User")
        self.tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="member")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

    def test_shows_running_version_tier_and_open_pull_requests(self):
        project = baker.make("app.Project", tenant=self.tenant, name="shop", platform=Platform.GITHUB)
        now = timezone.now()
        DeliverySettings.objects.create(project=project, strategy=DeploymentStrategy.RELEASE_TAGS, refreshed_at=now)
        baker.make(Deployment, project=project, strategy=DeploymentStrategy.RELEASE_TAGS, ref="v4.2.0",
                   external_id="v4.2.0", deployed_at=now - timedelta(hours=3))
        baker.make("app.PullRequest", project=project, number=1, state="open", created_at=now, updated_at=now)

        response = self.client.get(reverse("project_list"))

        self.assertContains(response, ">v4.2.0</a>")
        self.assertContains(response, 'data-group-tier="low"')
        self.assertContains(response, '<td class="text-center tabular-nums" data-project-open-pulls>1</td>', html=True)

    def test_a_project_not_synced_yet_shows_dashes_and_sorts_last(self):
        baker.make("app.Project", tenant=self.tenant, name="new", platform=Platform.GITHUB)

        response = self.client.get(reverse("project_list"))

        self.assertContains(response, 'data-sort-deploys=""')
        self.assertContains(response, 'data-group-tier=""')
