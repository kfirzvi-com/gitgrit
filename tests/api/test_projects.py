from model_bakery import baker
from rest_framework.test import APITestCase


class TestSearchProjectsAPI(APITestCase):
    url = "/api/projects/search/"

    def test_unauthenticated_request_redirects(self):
        response = self.client.get(self.url)
        assert response.status_code == 302

    def test_authenticated_no_tenant_returns_empty_results(self):
        user = baker.make("app.User")
        self.client.force_login(user)
        # No membership → TenantMiddleware sets request.tenant = None
        response = self.client.get(self.url, {"q": "test"})
        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_authenticated_missing_connection_id_returns_empty_results(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant)
        self.client.force_login(user)

        response = self.client.get(self.url, {"q": "test"})
        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_authenticated_invalid_connection_id_returns_empty_results(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant)
        self.client.force_login(user)

        response = self.client.get(
            self.url,
            {"q": "test", "connection_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_connection_belonging_to_other_tenant_returns_empty_results(self):
        user = baker.make("app.User")
        tenant = baker.make("app.Tenant")
        other_tenant = baker.make("app.Tenant")
        baker.make("app.Membership", user=user, tenant=tenant)
        other_connection = baker.make(
            "app.PlatformConnection", tenant=other_tenant, platform="github"
        )
        self.client.force_login(user)

        response = self.client.get(
            self.url,
            {"q": "test", "connection_id": str(other_connection.id)},
        )
        assert response.status_code == 200
        assert response.json()["results"] == []
