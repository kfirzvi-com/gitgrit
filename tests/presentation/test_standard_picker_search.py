"""Standards table on the project page: label wording, smart search
(`category:value`), label chip click, and the combined Filter dropdown (Connection + Critical groups).

The filtering runs in the browser. The pure parser/matcher lives in
app/static/app/standard-search.js and is unit-tested by running it in node
(skipped when node is missing); the rendered markup is checked through the view.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from django.test import TestCase
from django.urls import reverse
from model_bakery import baker

from tests.presentation.test_project_critical_marks import (
    _login_member,
    _project,
    _standard,
)

JS = Path(__file__).resolve().parents[2] / "app/static/app/standard-search.js"
NODE = shutil.which("node")

ROW = {
    "search": "secrets scan finds keys security",
    "name": "secrets scan",
    "description": "finds keys",
    "labels": ["security", "my label"],
    "status": "active",
    "critical": True,
    "connected": False,
}


def _js(expr):
    script = (
        f"const s = require({json.dumps(str(JS))});"
        f"console.log(JSON.stringify({expr}));"
    )
    out = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, check=True
    ).stdout
    return json.loads(out)


def _matches(query, row=ROW):
    return _js(
        f"s.matchStandardRow(s.parseStandardSearch({json.dumps(query)}), {json.dumps(row)})"
    )


@pytest.mark.skipif(NODE is None, reason="node not installed")
class TestSearchParser:
    def test_plain_text_is_kept_whole(self):
        parsed = _js('s.parseStandardSearch("  Secrets Scan ")')
        assert parsed == {"fields": [], "text": "secrets scan"}

    def test_category_value(self):
        parsed = _js('s.parseStandardSearch("name:secrets")')
        assert parsed == {"fields": [{"category": "name", "value": "secrets"}], "text": ""}

    def test_aliases_map_to_label(self):
        for word in ("label", "labels", "tag", "tags"):
            parsed = _js(f's.parseStandardSearch("{word}:x")')
            assert parsed["fields"] == [{"category": "label", "value": "x"}]

    def test_quoted_values_with_spaces(self):
        for query in ('name:"my std"', '"name:my std"'):
            parsed = _js(f"s.parseStandardSearch({json.dumps(query)})")
            assert parsed["fields"] == [{"category": "name", "value": "my std"}]

    def test_unknown_category_falls_back_to_plain_text(self):
        parsed = _js('s.parseStandardSearch("foo:bar")')
        assert parsed == {"fields": [], "text": "foo:bar"}

    def test_empty_value_is_plain_text(self):
        parsed = _js('s.parseStandardSearch("name:")')
        assert parsed == {"fields": [], "text": "name:"}

    def test_fields_and_free_text_combine(self):
        parsed = _js('s.parseStandardSearch("keys label:security")')
        assert parsed == {
            "fields": [{"category": "label", "value": "security"}],
            "text": "keys",
        }

    def test_matching_each_category(self):
        assert _matches("name:secrets")
        assert not _matches("name:keys")
        assert _matches("description:keys")
        assert _matches("label:security")
        assert _matches('label:"my label"')
        assert not _matches("label:other")
        assert _matches("status:active")
        assert not _matches("status:draft")
        assert _matches("critical:yes")
        assert not _matches("critical:no")
        assert _matches("connected:no")
        assert not _matches("connected:yes")

    def test_all_terms_must_match(self):
        assert _matches("name:secrets label:security")
        assert not _matches("name:secrets label:other")

    def test_label_chip_query(self):
        assert _js('s.labelSearchQuery("security")') == "label:security"
        assert _js('s.labelSearchQuery("my label")') == 'label:"my label"'


@pytest.mark.django_db
class TestPickerMarkup(TestCase):
    def _body(self):
        _, tenant = _login_member(self.client)
        project = _project(tenant)
        std = _standard(tenant, name="Secrets", description="Finds keys")
        label = baker.make("app.StandardLabel", tenant=tenant, name="Security")
        std.labels.add(label)
        resp = self.client.get(
            reverse("project_standards", args=[project.pk]),
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        return resp.content.decode()

    def test_ui_says_label_not_tag(self):
        body = self._body()
        assert ">Labels</button>" in body
        assert "Sort by first label" in body
        assert "Search for this label" in body
        assert "Tags</button>" not in body
        assert "by name, description, or tag" not in body
        assert "Filter by this tag" not in body

    def test_placeholder_shows_the_syntax(self):
        body = self._body()
        assert "try name:..., label:..." in body

    def test_label_chip_runs_a_search_in_the_table(self):
        body = self._body()
        assert 'data-tag="Security"' in body
        assert 'onclick="filterStandardPickerByTag(this)"' in body
        assert "labelSearchQuery" in body
        assert "app/standard-search.js" in body

    def test_row_carries_the_searchable_columns(self):
        body = self._body()
        assert 'data-labels="security|"' in body
        assert 'data-status="active"' in body
        assert 'data-description="finds keys"' in body

    def test_single_filter_with_two_groups_all_checked(self):
        body = self._body()
        assert "standard-picker-filter" in body
        assert "standard-picker-connected-filter" not in body
        assert "standard-picker-critical-filter" not in body
        assert "<select" not in body.split("standard-picker-filter", 1)[1].split("</details>")[0]
        for group, values in (
            ("connection", ("connected", "not-connected")),
            ("critical", ("critical", "not-critical")),
        ):
            for value in values:
                assert f'data-filter-group="{group}" value="{value}" checked' in body
        for text in ("Connection", "Not connected", "Not critical", "Reset"):
            assert text in body
        assert "standard-picker-filter-count" in body
        assert "resetStandardPickerFilter" in body
