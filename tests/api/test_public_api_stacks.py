"""Managing stacks over the public API: create, rename, delete, and which
projects belong to each. Any member can, as in the web app."""
from unittest.mock import patch

from model_bakery import baker

from app.domain.models import Project, Stack
from tests.api.test_public_api import PublicAPITestCase

PUBLISH = "app.application.stack_service.publish"


def _project(tenant, **kw):
    connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
    return baker.make("app.Project", tenant=tenant, platform_connection=connection, tags=[], languages=[], **kw)


class TestStackManagement(PublicAPITestCase):
    def test_create_rename_and_delete(self):
        r = self.send("post", f"{self.ws}/stacks/", {"name": " Payments ", "description": "Money"})
        assert r.status_code == 201, r.content
        stack = r.json()
        assert (stack["name"], stack["description"], stack["project_count"]) == ("Payments", "Money", 0)

        r = self.send("patch", f"{self.ws}/stacks/{stack['id']}/", {"name": "Billing"})
        assert r.status_code == 200
        assert (r.json()["name"], r.json()["description"]) == ("Billing", "Money")

        assert self.send("delete", f"{self.ws}/stacks/{stack['id']}/").status_code == 204
        assert not Stack.objects.exists()

    def test_a_stack_needs_a_name(self):
        assert self.send("post", f"{self.ws}/stacks/", {"name": "  "}).status_code == 400
        stack = baker.make("app.Stack", tenant=self.tenant, name="Web")
        assert self.send("patch", f"{self.ws}/stacks/{stack.pk}/", {"name": " "}).status_code == 400

    def test_members_manage_stacks(self):
        member = baker.make("app.User")
        baker.make("app.Membership", user=member, tenant=self.tenant, role="member")
        from tests.api.test_public_api import make_oauth_token

        self.auth = {"Authorization": f"Bearer {make_oauth_token(member)}"}
        assert self.send("post", f"{self.ws}/stacks/", {"name": "Web"}).status_code == 201

    def test_another_workspaces_stack_is_404(self):
        other = baker.make("app.Stack", tenant=baker.make("app.Tenant"))
        assert self.send("patch", f"{self.ws}/stacks/{other.pk}/", {"name": "x"}).status_code == 404
        assert self.send("delete", f"{self.ws}/stacks/{other.pk}/").status_code == 404


class TestStackProjects(PublicAPITestCase):
    def setUp(self):
        super().setUp()
        self.stack = baker.make("app.Stack", tenant=self.tenant, name="Orders")
        self.api = _project(self.tenant, name="api", full_path="acme/api")
        self.orders = _project(self.tenant, name="mono/services/orders", full_path="acme/mono",
                               root_path="services/orders")

    def test_add_and_remove_projects_with_their_events(self):
        url = f"{self.ws}/stacks/{self.stack.pk}/projects/"
        with patch(PUBLISH) as publish:
            r = self.send("post", url, {"project_ids": [str(self.api.pk), str(self.orders.pk)]})
            again = self.send("post", url, {"project_ids": [str(self.api.pk)]})

        assert (r.json(), again.json()) == ({"added": 2}, {"added": 0})
        assert set(Project.objects.filter(stacks=self.stack)) == {self.api, self.orders}
        assert [type(c.args[0]).__name__ for c in publish.call_args_list] == ["ProjectAddedToStack"] * 2

        with patch(PUBLISH) as publish:
            assert self.send("delete", f"{url}{self.orders.pk}/").status_code == 204
            assert self.send("delete", f"{url}{self.orders.pk}/").status_code == 404  # no longer in it
        assert set(Project.objects.filter(stacks=self.stack)) == {self.api}
        assert type(publish.call_args.args[0]).__name__ == "ProjectRemovedFromStack"

    def test_the_stack_lists_its_projects_with_their_paths(self):
        self.orders.stacks.add(self.stack)
        body = self.get(f"{self.ws}/stacks/{self.stack.pk}/").json()
        [row] = body["projects"]
        assert (row["name"], row["full_path"], row["root_path"]) == ("mono/services/orders", "acme/mono", "services/orders")

    def test_another_workspaces_project_is_404_and_nothing_is_added(self):
        foreign = _project(baker.make("app.Tenant"))

        r = self.send("post", f"{self.ws}/stacks/{self.stack.pk}/projects/",
                      {"project_ids": [str(self.orders.pk), str(foreign.pk)]})

        assert r.status_code == 404
        assert not Project.objects.filter(stacks=self.stack).exists()
