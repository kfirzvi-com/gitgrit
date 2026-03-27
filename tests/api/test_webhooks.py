from model_bakery import baker
from rest_framework.test import APITestCase

from app.domain.models import PolicyExecution


class TestGitHubWebhookView(APITestCase):
    url = "/api/webhooks/github/"

    def _post(self, payload, event="push"):
        return self.client.post(
            self.url,
            data=payload,
            format="json",
            HTTP_X_GITHUB_EVENT=event,
        )

    def test_no_matching_project_returns_empty_results(self):
        payload = {
            "repository": {"id": 99999},
            "ref": "refs/heads/main",
            "sender": {"login": "octocat"},
        }
        response = self._post(payload)
        assert response.status_code == 200
        assert response.data["platform"] == "github"
        assert response.data["event_type"] == "push"
        assert response.data["external_project_id"] == "99999"
        assert response.data["policies_run"] == 0
        assert response.data["results"] == []

    def test_matching_project_no_policies_returns_zero_policies_run(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        baker.make("app.Project", tenant=tenant, platform_connection=connection, platform="github", external_id="42")

        response = self._post({"repository": {"id": 42}, "sender": {"login": "octocat"}})
        assert response.status_code == 200
        assert response.data["policies_run"] == 0
        assert response.data["results"] == []

    def test_matching_project_with_policy_creates_execution_record(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        project = baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=connection,
            platform="github",
            external_id="100",
        )
        policy = baker.make(
            "app.Policy",
            tenant=tenant,
            enabled=True,
            draft=False,
            criteria={"events": ["push"]},
        )

        response = self._post(
            {"repository": {"id": 100}, "ref": "refs/heads/main", "sender": {"login": "octocat"}}
        )

        assert response.status_code == 200
        assert response.data["policies_run"] == 1

        result = response.data["results"][0]
        assert result["policy_name"] == policy.name
        assert result["project_name"] == project.name

        execution = PolicyExecution.objects.get(project=project, policy=policy)
        assert execution.event_type == "push"
        assert execution.triggered_by == "octocat"
        assert execution.ref == "refs/heads/main"
        assert execution.status in PolicyExecution.Status.values

    def test_policy_not_matching_event_is_skipped(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        project = baker.make(
            "app.Project", tenant=tenant, platform_connection=connection, platform="github", external_id="111"
        )
        baker.make(
            "app.Policy",
            tenant=tenant,
            enabled=True,
            draft=False,
            criteria={"events": ["release"]},  # only matches "release", not "push"
        )

        response = self._post({"repository": {"id": 111}, "sender": {"login": "octocat"}})
        assert response.status_code == 200
        assert response.data["policies_run"] == 0
        assert not PolicyExecution.objects.filter(project=project).exists()

    def test_disabled_policy_is_not_run(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        project = baker.make(
            "app.Project", tenant=tenant, platform_connection=connection, platform="github", external_id="222"
        )
        baker.make(
            "app.Policy",
            tenant=tenant,
            enabled=False,
            draft=False,
            criteria={"events": ["push"]},
        )

        response = self._post({"repository": {"id": 222}, "sender": {"login": "octocat"}})
        assert response.status_code == 200
        assert response.data["policies_run"] == 0
        assert not PolicyExecution.objects.filter(project=project).exists()

    def test_draft_policy_is_not_run(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        project = baker.make(
            "app.Project", tenant=tenant, platform_connection=connection, platform="github", external_id="333"
        )
        baker.make(
            "app.Policy",
            tenant=tenant,
            enabled=True,
            draft=True,
            criteria={"events": ["push"]},
        )

        response = self._post({"repository": {"id": 333}, "sender": {"login": "octocat"}})
        assert response.status_code == 200
        assert response.data["policies_run"] == 0
        assert not PolicyExecution.objects.filter(project=project).exists()

    def test_pull_request_event_maps_to_merge_request(self):
        response = self._post({"repository": {"id": 77777}, "sender": {"login": "octocat"}}, event="pull_request")
        assert response.status_code == 200
        assert response.data["event_type"] == "merge_request"

    def test_unknown_event_passes_through_unchanged(self):
        response = self._post({"repository": {"id": 88888}, "sender": {"login": "octocat"}}, event="deployment")
        assert response.status_code == 200
        assert response.data["event_type"] == "deployment"

    def test_multiple_policies_all_executed(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        project = baker.make(
            "app.Project", tenant=tenant, platform_connection=connection, platform="github", external_id="444"
        )
        baker.make("app.Policy", tenant=tenant, enabled=True, draft=False, criteria={"events": ["push"]}, _quantity=3)

        response = self._post({"repository": {"id": 444}, "ref": "refs/heads/main", "sender": {"login": "octocat"}})
        assert response.status_code == 200
        assert response.data["policies_run"] == 3
        assert PolicyExecution.objects.filter(project=project).count() == 3

    def test_policy_from_different_tenant_is_not_run(self):
        tenant = baker.make("app.Tenant")
        other_tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        project = baker.make(
            "app.Project", tenant=tenant, platform_connection=connection, platform="github", external_id="555"
        )
        baker.make(
            "app.Policy",
            tenant=other_tenant,
            enabled=True,
            draft=False,
            criteria={"events": ["push"]},
        )

        response = self._post({"repository": {"id": 555}, "sender": {"login": "octocat"}})
        assert response.status_code == 200
        assert response.data["policies_run"] == 0
        assert not PolicyExecution.objects.filter(project=project).exists()


class TestGitLabWebhookView(APITestCase):
    url = "/api/webhooks/gitlab/"

    def _post(self, payload):
        return self.client.post(self.url, data=payload, format="json")

    def test_no_matching_project_returns_empty_results(self):
        payload = {
            "object_kind": "push",
            "project_id": 55555,
            "project": {"id": 55555},
            "user_username": "gitlabuser",
            "ref": "refs/heads/main",
        }
        response = self._post(payload)
        assert response.status_code == 200
        assert response.data["platform"] == "gitlab"
        assert response.data["event_type"] == "push"
        assert response.data["external_project_id"] == "55555"
        assert response.data["policies_run"] == 0

    def test_matching_project_no_policies_returns_zero_policies_run(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="gitlab")
        baker.make(
            "app.Project", tenant=tenant, platform_connection=connection, platform="gitlab", external_id="200"
        )

        response = self._post(
            {"object_kind": "push", "project_id": 200, "project": {"id": 200}, "user_username": "gitlabuser"}
        )
        assert response.status_code == 200
        assert response.data["policies_run"] == 0

    def test_event_name_takes_precedence_over_object_kind(self):
        response = self._post(
            {"event_name": "tag_push", "object_kind": "push", "project_id": 66666, "project": {"id": 66666}}
        )
        assert response.status_code == 200
        assert response.data["event_type"] == "tag_push"

    def test_matching_project_with_policy_creates_execution_record(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="gitlab")
        project = baker.make(
            "app.Project", tenant=tenant, platform_connection=connection, platform="gitlab", external_id="300"
        )
        policy = baker.make(
            "app.Policy",
            tenant=tenant,
            enabled=True,
            draft=False,
            criteria={"events": ["push"]},
        )

        response = self._post(
            {
                "object_kind": "push",
                "project_id": 300,
                "project": {"id": 300},
                "user_username": "gitlabuser",
                "ref": "refs/heads/main",
            }
        )

        assert response.status_code == 200
        assert response.data["policies_run"] == 1

        result = response.data["results"][0]
        assert result["policy_name"] == policy.name
        assert result["project_name"] == project.name

        execution = PolicyExecution.objects.get(project=project, policy=policy)
        assert execution.event_type == "push"
        assert execution.triggered_by == "gitlabuser"
        assert execution.status in PolicyExecution.Status.values
