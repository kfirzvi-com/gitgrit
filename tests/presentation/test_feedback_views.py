import json

import pytest
from django.test import TestCase
from model_bakery import baker

from app.domain.models import FeedbackReport


@pytest.mark.django_db
class TestSubmitFeedback(TestCase):
    url = "/feedback/"

    def test_anonymous_post_redirects_to_login(self):
        response = self.client.post(self.url, {"body": "hi"})
        assert response.status_code == 302

    def test_get_method_not_allowed(self):
        user = baker.make("app.User")
        self.client.force_login(user)

        response = self.client.get(self.url)
        assert response.status_code == 405

    def test_empty_body_returns_400(self):
        user = baker.make("app.User")
        self.client.force_login(user)

        response = self.client.post(self.url, {"body": ""})
        assert response.status_code == 400
        assert FeedbackReport.objects.count() == 0

    def test_whitespace_only_body_returns_400(self):
        user = baker.make("app.User")
        self.client.force_login(user)

        response = self.client.post(self.url, {"body": "   \n\t  "})
        assert response.status_code == 400
        assert FeedbackReport.objects.count() == 0

    def test_oversize_body_returns_400(self):
        user = baker.make("app.User")
        self.client.force_login(user)

        response = self.client.post(self.url, {"body": "x" * 4001})
        assert response.status_code == 400
        assert FeedbackReport.objects.count() == 0

    def test_invalid_json_context_returns_400(self):
        user = baker.make("app.User")
        self.client.force_login(user)

        response = self.client.post(self.url, {"body": "hi", "context": "not-json"})
        assert response.status_code == 400
        assert FeedbackReport.objects.count() == 0

    def test_non_dict_json_context_returns_400(self):
        user = baker.make("app.User")
        self.client.force_login(user)

        for payload in ("[1, 2, 3]", "\"a string\"", "42", "null"):
            response = self.client.post(self.url, {"body": "hi", "context": payload})
            assert response.status_code == 400, payload
        assert FeedbackReport.objects.count() == 0

    def test_oversize_context_returns_400(self):
        user = baker.make("app.User")
        self.client.force_login(user)

        oversize = '{"x":"' + "a" * 9000 + '"}'
        response = self.client.post(self.url, {"body": "hi", "context": oversize})
        assert response.status_code == 400
        assert FeedbackReport.objects.count() == 0

    def test_happy_path_persists_row_without_tenant(self):
        user = baker.make("app.User", email="dev@example.com")
        self.client.force_login(user)

        response = self.client.post(
            self.url,
            {
                "body": "Found a bug in the policy editor.",
                "context": json.dumps({"url": "http://x/y", "viewport": "800x600"}),
            },
        )
        assert response.status_code == 200

        fb = FeedbackReport.objects.get()
        assert fb.body == "Found a bug in the policy editor."
        assert fb.user_id == user.id
        assert fb.user_email == "dev@example.com"
        assert fb.tenant_slug == ""
        assert fb.context == {"url": "http://x/y", "viewport": "800x600"}

    def test_happy_path_captures_tenant_slug_when_membership_exists(self):
        user = baker.make("app.User", email="dev@example.com")
        tenant = baker.make("app.Tenant", slug="acme")
        baker.make("app.Membership", user=user, tenant=tenant)
        self.client.force_login(user)

        response = self.client.post(self.url, {"body": "Workspace feedback."})
        assert response.status_code == 200

        fb = FeedbackReport.objects.get()
        assert fb.tenant_slug == "acme"

    def test_empty_context_string_persists_empty_dict(self):
        user = baker.make("app.User")
        self.client.force_login(user)

        response = self.client.post(self.url, {"body": "hi", "context": ""})
        assert response.status_code == 200

        fb = FeedbackReport.objects.get()
        assert fb.context == {}

    def test_body_is_stripped(self):
        user = baker.make("app.User")
        self.client.force_login(user)

        response = self.client.post(self.url, {"body": "  surrounded by space  "})
        assert response.status_code == 200

        fb = FeedbackReport.objects.get()
        assert fb.body == "surrounded by space"
