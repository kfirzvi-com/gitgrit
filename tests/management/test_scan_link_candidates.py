"""``scan_link_candidates``: the JSONL case file and its summary, run against
the small messy-monorepo fixture with a golden that names its components."""
from __future__ import annotations

import json
import uuid
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from model_bakery import baker

from tests.support import TmpPathMixin

REPO_ROOT = Path(__file__).resolve().parents[2]
MINI = REPO_ROOT / "tests" / "fixtures" / "links" / "messy_mini"

GOLDEN = {
    "components": [
        {"path": "apps/api-gateway", "name": "api-gateway", "kind": "service"},
        {"path": "frontend/web-storefront", "name": "web-storefront", "kind": "frontend"},
        {"path": "services/auth-service", "name": "auth-service", "kind": "service"},
        {"path": "services/orders-service", "name": "orders-service", "kind": "service"},
    ],
    "internal": [{"source_path": "apps/api-gateway", "target_ref": "{repo}#services/auth-service", "label": "REST"}],
    "externals": [],
    "infrastructure": [],
    "evidence": {"files_read": ["README.md"]},
}


class TestScanLinkCandidates(TmpPathMixin, TestCase):
    def setUp(self):
        super().setUp()
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        self.project = baker.make(
            "app.Project", tenant=tenant, platform_connection=conn,
            name="gitgrit-demo-messy-monorepo", full_path="kfirzvi-com/gitgrit-demo-messy-monorepo",
        )
        baker.make(  # another workspace repository the compose image points at
            "app.Project", tenant=tenant, platform_connection=conn,
            name="gitgrit-demo-payments-service", full_path="kfirzvi-com/gitgrit-demo-payments-service",
        )
        self.golden = self.tmp_path / "golden.json"
        self.golden.write_text(json.dumps(GOLDEN))
        self.out = self.tmp_path / "cases.jsonl"

    def run_command(self, project_id, *extra):
        stdout = StringIO()
        call_command(
            "scan_link_candidates", str(project_id),
            "--local-path", str(MINI), "--fixture", str(self.golden), "--out", str(self.out),
            *extra, stdout=stdout, stderr=StringIO(),
        )
        return stdout.getvalue()

    def test_writes_one_json_case_per_line_with_empty_expectations(self):
        text = self.run_command(self.project.id)

        rows = [json.loads(line) for line in self.out.read_text(encoding="utf-8").splitlines()]
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertEqual((row["expected_target"], row["expected_kind"]), ("", ""))
            self.assertIsInstance(row["options"], list)
            for option in row["options"]:
                self.assertEqual(set(option), {"id", "ref", "name", "kind"})
            self.assertIn(row["reference_kind"], text)

        by_key = {(r["source_path"], r["reference_kind"], r["reference"]) for r in rows}
        self.assertIn(("apps/api-gateway", "compose_depends_on", "auth-service"), by_key)
        self.assertIn(("apps/api-gateway", "env_var", "AUTH_SERVICE_URL"), by_key)
        image = next(r for r in rows if r["reference_kind"] == "image")
        # The workspace roster (the other project) ranks first, ahead of the golden's siblings.
        self.assertEqual(image["options"][0]["ref"], "kfirzvi-com/gitgrit-demo-payments-service")
        sibling = next(r for r in rows if r["reference"] == "auth-service" and r["reference_kind"] == "compose_depends_on")
        self.assertEqual(sibling["options"][0]["ref"], f"{self.project.full_path}#services/auth-service")

        self.assertRegex(text, rf"{len(rows)} candidates from \d+ files -> {self.out}")
        counts = dict(line.split() for line in text.splitlines()[1:])
        self.assertEqual(sum(int(n) for n in counts.values()), len(rows))
        self.assertIn("compose_depends_on", counts)

    def test_limit_caps_the_case_file(self):
        self.run_command(self.project.id, "--limit", "2")
        self.assertEqual(len(self.out.read_text().splitlines()), 2)

    def test_unknown_or_malformed_project_id_is_a_command_error(self):
        missing = uuid.uuid4()
        with self.assertRaisesRegex(CommandError, f"No such project: {missing}"):
            self.run_command(missing)
        with self.assertRaisesRegex(CommandError, "No such project: nope"):
            self.run_command("nope")
        self.assertFalse(self.out.exists())
