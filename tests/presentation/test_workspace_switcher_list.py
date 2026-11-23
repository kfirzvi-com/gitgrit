"""The navbar workspace switcher lazy-loads and searches its rows.

Rows come from ``workspace_switcher_list`` and must only ever be the user's
own memberships: this endpoint is the one place a foreign workspace could
leak into the switcher. The context processor no longer ships the full list
with every page; it sends a count and decides whether the search box shows.
"""
import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from model_bakery import baker

from app.context_processors import WORKSPACE_SEARCH_THRESHOLD
from app.presentation.views.workspace_switcher_views import ROW_LIMIT

NON_MANIFEST_STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


def _login(client, tenant_name="Home"):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant", name=tenant_name, slug="home")
    baker.make("app.Membership", user=user, tenant=tenant, role="owner")
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return user, tenant


def _join(user, name, slug=None, **kwargs):
    tenant = baker.make("app.Tenant", name=name, slug=slug or name.lower().replace(" ", "-"))
    baker.make("app.Membership", user=user, tenant=tenant, **kwargs)
    return tenant


@pytest.mark.django_db
class TestWorkspaceSwitcherList(TestCase):
    url = reverse("workspace_switcher_list")

    def test_lists_only_workspaces_the_user_belongs_to(self):
        user, _ = _login(self.client)
        mine = _join(user, "Acme Corp")
        foreign = baker.make("app.Tenant", name="Foreign Inc", slug="foreign")

        html = self.client.get(self.url).content.decode()

        assert mine.name in html
        assert foreign.name not in html
        assert str(foreign.id) not in html

    def test_search_never_returns_foreign_workspaces(self):
        _login(self.client)
        baker.make("app.Tenant", name="Secret Client", slug="secret-client")

        html = self.client.get(self.url, {"q": "secret"}).content.decode()

        assert "Secret Client" not in html
        assert "No workspace matches" in html

    def test_search_filters_by_name_case_insensitively(self):
        user, _ = _login(self.client)
        _join(user, "Acme Corp")
        _join(user, "Beta Ltd")

        html = self.client.get(self.url, {"q": "ACME"}).content.decode()

        assert "Acme Corp" in html
        assert "Beta Ltd" not in html

    def test_search_filters_by_slug(self):
        user, _ = _login(self.client)
        _join(user, "Room One", slug="roomone-prod")
        _join(user, "Beta Ltd")

        html = self.client.get(self.url, {"q": "roomone"}).content.decode()

        assert "Room One" in html
        assert "Beta Ltd" not in html

    def test_current_workspace_comes_first_and_is_marked_active(self):
        user, current = _login(self.client, tenant_name="Zulu")
        _join(user, "Alpha")

        html = self.client.get(self.url).content.decode()

        assert html.index("Zulu") < html.index("Alpha")
        assert 'class="active' in html

    def test_caps_rows_and_reports_remaining(self):
        user, _ = _login(self.client)
        for i in range(ROW_LIMIT + 3):
            _join(user, f"Workspace {i:02d}")

        html = self.client.get(self.url).content.decode()

        assert "3 more" in html
        assert "Workspace 00" in html
        assert f"Workspace {ROW_LIMIT + 2:02d}" not in html

    def test_shows_slug_to_disambiguate_same_names(self):
        user, _ = _login(self.client)
        _join(user, "Acme", slug="acme-client")
        _join(user, "Acme", slug="acme-internal")

        html = self.client.get(self.url).content.decode()

        assert "acme-client" in html
        assert "acme-internal" in html

    def test_post_is_rejected(self):
        _login(self.client)

        response = self.client.post(self.url)

        assert response.status_code == 405

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get(self.url)

        assert response.status_code == 302
        assert response.headers["Location"].startswith(reverse("account_login"))


@pytest.mark.django_db
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class TestNavbarSwitcher(TestCase):
    def test_pages_do_not_inline_the_workspace_list(self):
        user, _ = _login(self.client)
        other = _join(user, "Lazy Loaded Workspace")

        html = self.client.get(reverse("dashboard")).content.decode()

        assert other.name not in html
        assert reverse("workspace_switcher_list") in html

    def test_search_box_hidden_for_few_workspaces(self):
        _login(self.client)

        html = self.client.get(reverse("dashboard")).content.decode()

        assert "Find workspace" not in html

    def test_search_box_shown_above_threshold(self):
        user, _ = _login(self.client)
        for i in range(WORKSPACE_SEARCH_THRESHOLD):
            _join(user, f"W{i}")

        html = self.client.get(reverse("dashboard")).content.decode()

        assert "Find workspace" in html


def _rows(html, *names):
    return [html.index(n) for n in names]


@pytest.mark.django_db
class TestSupportWorkspacesLast(TestCase):
    url = reverse("workspace_switcher_list")

    def test_superuser_sees_own_workspaces_before_support_ones(self):
        user, _ = _login(self.client)
        user.is_superuser = True
        user.save()
        _join(user, "Zulu Mine")
        baker.make("app.Tenant", name="Alpha Support", slug="alpha-support")

        html = self.client.get(self.url).content.decode()

        zulu, alpha = _rows(html, "Zulu Mine", "Alpha Support")
        assert zulu < alpha
        assert html.index(">Support<") < alpha


@pytest.mark.django_db
class TestPinnedWorkspaces(TestCase):
    url = reverse("workspace_switcher_list")
    pin_url = reverse("toggle_workspace_pin")

    def test_pinned_workspace_leads_the_list(self):
        user, _ = _login(self.client)
        _join(user, "Alpha")
        zulu = _join(user, "Zulu")
        baker.make("app.WorkspacePin", user=user, tenant=zulu)

        html = self.client.get(self.url).content.decode()

        zulu_at, alpha_at = _rows(html, "Zulu", "Alpha")
        assert html.index(">Pinned<") < zulu_at < alpha_at

    def test_pins_are_per_user(self):
        user, _ = _login(self.client)
        _join(user, "Alpha")
        zulu = _join(user, "Zulu")
        baker.make("app.WorkspacePin", user=baker.make("app.User"), tenant=zulu)

        html = self.client.get(self.url).content.decode()

        assert ">Pinned<" not in html
        assert html.index("Alpha") < html.index("Zulu")

    def test_pinned_support_workspace_comes_before_own(self):
        user, _ = _login(self.client)
        user.is_superuser = True
        user.save()
        _join(user, "Alpha Mine")
        support = baker.make("app.Tenant", name="Zulu Support", slug="zulu-support")
        baker.make("app.WorkspacePin", user=user, tenant=support)

        html = self.client.get(self.url).content.decode()

        assert html.index("Zulu Support") < html.index("Alpha Mine")

    def test_toggle_pins_then_unpins(self):
        user, _ = _login(self.client)
        zulu = _join(user, "Zulu")

        html = self.client.post(self.pin_url, {"tenant_id": str(zulu.id)}).content.decode()
        assert user.workspace_pins.filter(tenant=zulu).exists()
        assert "Unpin Zulu" in html

        html = self.client.post(self.pin_url, {"tenant_id": str(zulu.id)}).content.decode()
        assert not user.workspace_pins.exists()
        assert "Pin Zulu" in html

    def test_toggle_keeps_the_search(self):
        user, _ = _login(self.client)
        acme = _join(user, "Acme")
        _join(user, "Beta")

        html = self.client.post(
            self.pin_url, {"tenant_id": str(acme.id), "q": "acme"}
        ).content.decode()

        assert "Acme" in html
        assert "Beta" not in html

    def test_cannot_pin_a_foreign_workspace(self):
        user, _ = _login(self.client)
        foreign = baker.make("app.Tenant", name="Foreign", slug="foreign")

        response = self.client.post(self.pin_url, {"tenant_id": str(foreign.id)})

        assert response.status_code == 404
        assert not user.workspace_pins.exists()

    def test_superuser_can_pin_a_support_workspace(self):
        user, _ = _login(self.client)
        user.is_superuser = True
        user.save()
        support = baker.make("app.Tenant", name="Support Co", slug="support-co")

        response = self.client.post(self.pin_url, {"tenant_id": str(support.id)})

        assert response.status_code == 200
        assert user.workspace_pins.filter(tenant=support).exists()

    def test_bad_tenant_id_is_404(self):
        _login(self.client)

        assert self.client.post(self.pin_url, {"tenant_id": "nope"}).status_code == 404

    def test_pin_is_post_only(self):
        _login(self.client)

        assert self.client.get(self.pin_url).status_code == 405

    def test_pin_survives_losing_access_but_stops_showing(self):
        user, _ = _login(self.client)
        gone = _join(user, "Gone Co")
        baker.make("app.WorkspacePin", user=user, tenant=gone)
        user.memberships.filter(tenant=gone).delete()

        html = self.client.get(self.url).content.decode()

        assert "Gone Co" not in html
