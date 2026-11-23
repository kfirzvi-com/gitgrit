"""Suggested projects: the apps and services found inside a monorepo, each
one click away from being a project of its own rooted at its directory."""
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.application.project_suggestions import ProjectSuggestions
from app.domain.models import AuthMethod, Project

SUGGESTIONS = [
    {"path": "apps/web", "name": "web", "kind": "frontend", "description": "Storefront",
     "technologies": ["Next.js"], "stack_ids": []},
    {"path": "services/orders", "name": "orders", "kind": "service", "description": "", "technologies": []},
]


def _client():
    client = mock.Mock()
    client.get_tree.return_value = ["apps/web/src/a.ts", "services/orders/main.go"]
    client.get_topics.return_value = []
    return client


class _Fixture(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        conn = baker.make(
            "app.PlatformConnection", tenant=self.tenant, platform="github", auth_method=AuthMethod.GITHUB_APP
        )
        self.mono = baker.make(
            "app.Project", tenant=self.tenant, platform_connection=conn, external_id="9", name="shop",
            full_path="acme/shop", web_url="https://github.com/acme/shop", owner="Platform team",
            suggested_projects=SUGGESTIONS,
        )
        patch = mock.patch("app.application.project_management.get_platform_client", return_value=_client())
        patch.start()
        self.addCleanup(patch.stop)


class ProjectSuggestionsTests(_Fixture):
    def test_adding_one_makes_a_rooted_project_with_the_suggestions_details(self):
        stack = baker.make("app.Stack", tenant=self.tenant)
        self.mono.suggested_projects = [{**SUGGESTIONS[0], "stack_ids": [str(stack.pk)]}, SUGGESTIONS[1]]
        self.mono.save()

        result = ProjectSuggestions(self.mono).add(["apps/web"])

        [web] = result.added
        self.assertEqual((web.full_path, web.root_path, web.name), ("acme/shop", "apps/web", "shop/apps/web"))
        self.assertEqual((web.kind, web.technologies, web.description), ("frontend", ["Next.js"], "Storefront"))
        self.assertEqual(web.owner, "Platform team")
        self.assertEqual(web.languages, ["TypeScript"])
        self.assertEqual(list(web.stacks.all()), [stack])
        self.assertEqual([s.path for s in self.mono.open_suggestions()], ["services/orders"])

    def test_adding_all_skips_paths_that_are_projects_already(self):
        ProjectSuggestions(self.mono).add(["apps/web"])

        result = ProjectSuggestions(self.mono).add(None)

        self.assertEqual([p.root_path for p in result.added], ["services/orders"])
        self.assertEqual(self.mono.open_suggestions(), [])
        self.assertEqual(Project.objects.filter(full_path="acme/shop").count(), 3)

    def test_a_path_not_suggested_is_not_added(self):
        result = ProjectSuggestions(self.mono).add(["nowhere"])
        self.assertEqual((result.added, result.already), ((), 1))


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class AddSuggestedProjectsViewTests(_Fixture):
    def setUp(self):
        super().setUp()
        user = baker.make("app.User")
        baker.make("app.Membership", user=user, tenant=self.tenant, role="owner")
        self.client.force_login(user)
        session = self.client.session
        session["active_tenant_id"] = str(self.tenant.id)
        session.save()

    def test_the_project_page_offers_its_suggestions(self):
        body = self.client.get(reverse("project_detail", args=[self.mono.pk])).content.decode()
        self.assertIn("Suggested projects", body)
        self.assertIn(reverse("add_suggested_projects", args=[self.mono.pk]), body)
        self.assertIn('data-suggestion="services/orders"', body)

    def test_add_swaps_the_section_in_place_with_a_toast(self):
        response = self.client.post(
            reverse("add_suggested_projects", args=[self.mono.pk]), {"path": "apps/web"}, headers={"HX-Request": "true"}
        )

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("shop/apps/web", body)  # now listed among the repository's projects
        self.assertNotIn('data-suggestion="apps/web"', body)
        self.assertIn('data-suggestion="services/orders"', body)
        self.assertIn("Added shop/apps/web.", response["HX-Trigger"])

    def test_add_all(self):
        response = self.client.post(
            reverse("add_suggested_projects", args=[self.mono.pk]), headers={"HX-Request": "true"}
        )
        self.assertNotIn("data-suggestion=", response.content.decode())
        self.assertEqual(Project.objects.filter(full_path="acme/shop").exclude(root_path="").count(), 2)
