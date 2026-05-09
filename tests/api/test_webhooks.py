import hashlib
import hmac
import json

from model_bakery import baker
from rest_framework.test import APITestCase

from app.domain.models import PolicyExecution


def _github_sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


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


class TestGitHubWebhookSignatureVerification(APITestCase):
    url = "/api/webhooks/github/"

    def _post_signed(self, payload: dict, secret: str | None, event: str = "push"):
        body = json.dumps(payload).encode()
        kwargs = {
            "data": body,
            "content_type": "application/json",
            "HTTP_X_GITHUB_EVENT": event,
        }
        if secret is not None:
            kwargs["HTTP_X_HUB_SIGNATURE_256"] = _github_sig(secret, body)
        return self.client.post(self.url, **kwargs)

    def test_valid_signature_is_accepted(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=connection,
            platform="github",
            external_id="700",
            webhook_secret="s3cret",
        )
        response = self._post_signed(
            {"repository": {"id": 700}, "sender": {"login": "octocat"}}, secret="s3cret"
        )
        assert response.status_code == 200

    def test_missing_signature_when_secret_configured_is_rejected(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=connection,
            platform="github",
            external_id="701",
            webhook_secret="s3cret",
        )
        response = self._post_signed(
            {"repository": {"id": 701}, "sender": {"login": "octocat"}}, secret=None
        )
        assert response.status_code == 401

    def test_wrong_signature_is_rejected(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=connection,
            platform="github",
            external_id="702",
            webhook_secret="s3cret",
        )
        response = self._post_signed(
            {"repository": {"id": 702}, "sender": {"login": "octocat"}}, secret="wrong"
        )
        assert response.status_code == 401

    def test_multi_tenant_any_matching_secret_accepts(self):
        # Two tenants registered the same external repo with their own secrets;
        # a webhook signed by tenant B's secret should validate.
        tenant_a = baker.make("app.Tenant")
        tenant_b = baker.make("app.Tenant")
        conn_a = baker.make("app.PlatformConnection", tenant=tenant_a, platform="github")
        conn_b = baker.make("app.PlatformConnection", tenant=tenant_b, platform="github")
        baker.make(
            "app.Project",
            tenant=tenant_a,
            platform_connection=conn_a,
            platform="github",
            external_id="703",
            webhook_secret="secret-a",
        )
        baker.make(
            "app.Project",
            tenant=tenant_b,
            platform_connection=conn_b,
            platform="github",
            external_id="703",
            webhook_secret="secret-b",
        )
        response = self._post_signed(
            {"repository": {"id": 703}, "sender": {"login": "octocat"}}, secret="secret-b"
        )
        assert response.status_code == 200

    def test_unsecured_legacy_project_is_accepted_unsigned(self):
        # Backward compat for v0.1: a project with empty webhook_secret accepts
        # unsigned requests (with a warning logged). Pre-launch fixes will
        # backfill secrets and tighten this to a 401.
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=connection,
            platform="github",
            external_id="704",
            webhook_secret="",
        )
        response = self._post_signed(
            {"repository": {"id": 704}, "sender": {"login": "octocat"}}, secret=None
        )
        assert response.status_code == 200

    def test_unsecured_legacy_project_ignores_invalid_signature(self):
        # If the project's webhook_secret is empty there is nothing to validate
        # against, so even a bogus signature header is accepted. This pins the
        # current intent so a future tightening of `unsecured` behavior surfaces
        # as a deliberate change rather than a silent regression.
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=connection,
            platform="github",
            external_id="705",
            webhook_secret="",
        )
        response = self._post_signed(
            {"repository": {"id": 705}, "sender": {"login": "octocat"}},
            secret="bogus-attacker-secret",
        )
        assert response.status_code == 200


class TestGitLabWebhookSignatureVerification(APITestCase):
    url = "/api/webhooks/gitlab/"

    def _post(self, payload: dict, token: str | None):
        kwargs = {"data": payload, "format": "json"}
        if token is not None:
            kwargs["HTTP_X_GITLAB_TOKEN"] = token
        return self.client.post(self.url, **kwargs)

    def _payload(self, external_id: int) -> dict:
        return {
            "object_kind": "push",
            "project_id": external_id,
            "project": {"id": external_id},
            "user_username": "gitlabuser",
        }

    def test_valid_token_is_accepted(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="gitlab")
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=connection,
            platform="gitlab",
            external_id="800",
            webhook_secret="gitlab-secret",
        )
        response = self._post(self._payload(800), token="gitlab-secret")
        assert response.status_code == 200

    def test_missing_token_when_secret_configured_is_rejected(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="gitlab")
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=connection,
            platform="gitlab",
            external_id="801",
            webhook_secret="gitlab-secret",
        )
        response = self._post(self._payload(801), token=None)
        assert response.status_code == 401

    def test_wrong_token_is_rejected(self):
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="gitlab")
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=connection,
            platform="gitlab",
            external_id="802",
            webhook_secret="gitlab-secret",
        )
        response = self._post(self._payload(802), token="wrong")
        assert response.status_code == 401

    def test_unsecured_legacy_project_is_accepted_without_token(self):
        # Mirror of the GitHub unsecured-project case: a v0.1 project that
        # predates the webhook_secret field is accepted unsigned with a warning.
        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="gitlab")
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=connection,
            platform="gitlab",
            external_id="803",
            webhook_secret="",
        )
        response = self._post(self._payload(803), token=None)
        assert response.status_code == 200


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
