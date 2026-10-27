"""Customer-controlled text never escapes into script (SOC 2 CC6.1, CC7.1).

Repository names and descriptions come from GitHub/GitLab; stack and
component names come from users and from LLM output over repository
contents. Each place that puts them inside a <script> block or an inline
event handler is checked with a payload that would run if it broke out.
"""
import html
import json
import re
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase, override_settings, tag
from django.urls import reverse
from model_bakery import baker

BREAKOUT = "</script><script>alert(1)</script>"
JS_STRING_BREAKOUT = "'),alert(1),('"
ATTR_BREAKOUT = "x' onmouseover='alert(1)' data-x='"
TAG = "<img src=x onerror=alert(1)>"

NON_MANIFEST_STORAGES = {
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def _login_member(client):
    user = baker.make("app.User")
    tenant = baker.make("app.Tenant")
    baker.make("app.Membership", user=user, tenant=tenant, role="owner")
    client.force_login(user)
    session = client.session
    session["active_tenant_id"] = str(tenant.id)
    session.save()
    return tenant


def _json_script(body, element_id):
    match = re.search(
        rf'<script id="{element_id}" type="application/json">(.*?)</script>', body, re.S
    )
    assert match, f"no #{element_id} block"
    return match.group(1)


@tag("security")
class RepositorySearchResultsTests(SimpleTestCase):
    result = {
        "external_id": "42",
        "name": TAG,
        "full_path": "acme/repo",
        "web_url": "https://github.com/acme/repo",
        "default_branch": "main",
        "description": ATTR_BREAKOUT + BREAKOUT,
    }

    def setUp(self):
        self.body = render_to_string(
            "partials/project_search_results.html", {"results": [self.result]}
        )

    def test_description_cannot_break_out_of_the_button_attributes(self):
        assert "onmouseover='alert" not in self.body
        assert "<script>alert" not in self.body
        assert TAG not in self.body

    def test_the_button_still_carries_the_whole_result(self):
        attr = re.search(r'data-project="([^"]*)"', self.body)
        assert attr, "result is passed in data-project"
        assert json.loads(html.unescape(attr.group(1))) == self.result


@tag("security")
class SelectedProjectSummaryTests(SimpleTestCase):
    """Source-level guard: the client-side summary has no HTML parsing."""

    def test_selected_repository_is_written_as_text_not_html(self):
        source = (Path(settings.BASE_DIR) / "app/templates/pages/add_project.html").read_text()
        body = source[source.index("function selectProject"):]
        body = body[: body.index("</script>")]
        assert "innerHTML" not in body


@tag("security")
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class ArchitectureDataTests(TestCase):
    def setUp(self):
        self.tenant = _login_member(self.client)
        self.stack = baker.make("app.Stack", tenant=self.tenant, name=BREAKOUT, description=TAG)
        connection = baker.make("app.PlatformConnection", tenant=self.tenant, platform="github")
        project = baker.make(
            "app.Project", tenant=self.tenant, platform_connection=connection,
            name=BREAKOUT, tags=[], languages=[],
        )
        # The stack page draws its graph only when the stack has components.
        project.root_component.stacks.add(self.stack)

    def _assert_safe(self, body, element_id):
        assert "<script>alert(1)" not in body
        data = json.loads(_json_script(body, element_id))
        assert BREAKOUT in json.dumps(data)  # the name survives, as data

    def test_dashboard_graph(self):
        response = self.client.get(reverse("dashboard"))
        assert response.status_code == 200
        self._assert_safe(response.content.decode(), "architecture-data")

    def test_stack_page_graph(self):
        response = self.client.get(reverse("stack_detail", args=[self.stack.pk]))
        assert response.status_code == 200
        self._assert_safe(response.content.decode(), "stack-architecture-data")


def _onclick_scripts(body):
    """The JavaScript each onclick attribute runs, as the browser sees it."""
    return [html.unescape(v) for v in re.findall(r'onclick="([^"]*)"', body)]


@tag("security")
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class ConfirmDialogNameTests(TestCase):
    """Names inside onclick="confirm('...')" stay inside the JS string: the
    browser decodes HTML entities before running the handler, so plain
    autoescaping is not enough there."""

    def setUp(self):
        self.tenant = _login_member(self.client)

    def _assert_no_breakout(self, url):
        response = self.client.get(url)
        assert response.status_code == 200
        scripts = _onclick_scripts(response.content.decode())
        assert any("confirm(" in s for s in scripts)
        for script in scripts:
            assert JS_STRING_BREAKOUT not in script, script

    def test_stack_delete(self):
        stack = baker.make("app.Stack", tenant=self.tenant, name=JS_STRING_BREAKOUT)
        self._assert_no_breakout(reverse("stack_detail", args=[stack.pk]))

    def test_project_remove(self):
        connection = baker.make("app.PlatformConnection", tenant=self.tenant, platform="github")
        project = baker.make(
            "app.Project", tenant=self.tenant, platform_connection=connection,
            name=JS_STRING_BREAKOUT, tags=[], languages=[],
        )
        self._assert_no_breakout(reverse("project_detail", args=[project.pk]))

    def test_standard_delete_on_detail_and_list(self):
        standard = baker.make(
            "app.Standard", tenant=self.tenant, name=JS_STRING_BREAKOUT, enabled=True, draft=False
        )
        self._assert_no_breakout(reverse("standard_detail", args=[standard.pk]))
        self._assert_no_breakout(reverse("standard_list"))


@tag("security")
@override_settings(STORAGES=NON_MANIFEST_STORAGES)
class ConnectionProjectNamesTests(TestCase):
    def test_remove_connection_lists_project_names_as_json(self):
        tenant = _login_member(self.client)
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        baker.make(
            "app.Project", tenant=tenant, platform_connection=connection,
            name=ATTR_BREAKOUT, tags=[], languages=[],
        )
        body = self.client.get(reverse("tenant_settings")).content.decode()
        attr = re.search(r'data-projects="([^"]*)"', body)
        assert attr, "connection carries its project names"
        assert json.loads(html.unescape(attr.group(1))) == [ATTR_BREAKOUT]


@tag("security")
class StandardFormEscapingTests(SimpleTestCase):
    """Source-level guard: every value the standard form writes into HTML
    (test-case names, sandbox results, errors) goes through escapeHtml."""

    def setUp(self):
        self.source = (Path(settings.BASE_DIR) / "app/templates/pages/standard_form.html").read_text()

    def test_interpolated_values_are_escaped(self):
        allowed = {"statusBadge", "matchBadge", "diffHtml"}  # markup we built
        for expr in re.findall(r"\$\{([^}]*)\}", self.source):
            expr = expr.strip()
            assert expr in allowed or expr.startswith("escapeHtml("), expr

    def test_error_message_is_escaped(self):
        assert "escapeHtml(err.message)" in self.source
        assert "+ err.message +" not in self.source


@tag("security")
class ProjectLinkTests(TestCase):
    def test_only_http_links_become_the_project_url(self):
        from app.application import project_management

        tenant = baker.make("app.Tenant")
        connection = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        repo = {"external_id": "1", "name": "r", "web_url": "javascript:alert(1)"}
        with self.assertRaises(ValueError):
            project_management.add_project(tenant, None, connection, repo)
