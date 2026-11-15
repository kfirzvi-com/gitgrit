"""Managing stacks over the public API: create, rename, delete, and which
components belong to each. Any member can, as in the web app."""
from unittest.mock import patch

from model_bakery import baker

from app.domain.models import Component, Stack
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


class TestStackComponents(PublicAPITestCase):
    def setUp(self):
        super().setUp()
        self.stack = baker.make("app.Stack", tenant=self.tenant, name="Orders")
        self.api = _project(self.tenant, name="api", full_path="acme/api")
        self.mono = _project(self.tenant, name="mono", full_path="acme/mono")
        self.orders = baker.make("app.Component", tenant=self.tenant, project=self.mono,
                                 path="services/orders", name="orders")

    def test_components_list_with_their_stacks(self):
        self.orders.stacks.add(self.stack)

        body = self.get(f"{self.ws}/components/").json()

        rows = {(c["project"]["full_path"], c["path"]): c for c in body}
        assert set(rows) == {("acme/api", ""), ("acme/mono", ""), ("acme/mono", "services/orders")}
        assert rows[("acme/mono", "services/orders")]["stacks"] == [{"id": str(self.stack.pk), "name": "Orders"}]
        only = self.get(f"{self.ws}/components/", project_id=str(self.api.pk)).json()
        assert [c["project"]["name"] for c in only] == ["api"]

    def test_add_and_remove_components_with_their_events(self):
        url = f"{self.ws}/stacks/{self.stack.pk}/components/"
        root = self.api.root_component
        with patch(PUBLISH) as publish:
            r = self.send("post", url, {"component_ids": [str(root.pk), str(self.orders.pk)]})
            again = self.send("post", url, {"component_ids": [str(root.pk)]})

        assert (r.json(), again.json()) == ({"added": 2}, {"added": 0})
        assert set(Component.objects.filter(stacks=self.stack)) == {root, self.orders}
        assert [type(c.args[0]).__name__ for c in publish.call_args_list] == ["ComponentAddedToStack"] * 2

        with patch(PUBLISH) as publish:
            assert self.send("delete", f"{url}{self.orders.pk}/").status_code == 204
            assert self.send("delete", f"{url}{self.orders.pk}/").status_code == 404  # no longer in it
        assert set(Component.objects.filter(stacks=self.stack)) == {root}
        assert type(publish.call_args.args[0]).__name__ == "ComponentRemovedFromStack"

    def test_another_workspaces_component_is_404_and_nothing_is_added(self):
        foreign = _project(baker.make("app.Tenant")).root_component

        r = self.send("post", f"{self.ws}/stacks/{self.stack.pk}/components/",
                      {"component_ids": [str(self.orders.pk), str(foreign.pk)]})

        assert r.status_code == 404
        assert not Component.objects.filter(stacks=self.stack).exists()
