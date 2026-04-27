from model_bakery import baker
from rest_framework.test import APITestCase

from app.application.edit_validator import EditValidator

_BAN_CONSOLE_LOG = '''
def evaluate(project):
    content = project.get_file_content("src/app.py")
    if content and "console.log" in content:
        return {"passed": False, "score": 0, "message": "no console.log", "details": {}}
    return {"passed": True, "score": 100, "message": "OK", "details": {}}
'''


class TestValidateEdit(APITestCase):
    def setUp(self):
        self.validator = EditValidator()
        self.tenant = baker.make("app.Tenant")
        self.project = baker.make(
            "app.Project", tenant=self.tenant, languages=["Python"]
        )
        baker.make(
            "app.Policy",
            tenant=self.tenant,
            name="no-console-log",
            code=_BAN_CONSOLE_LOG,
            enabled=True,
            draft=False,
            criteria={"languages": ["Python"]},
        )

    def test_introduced_violation_blocks(self):
        prior = "a console.log(1)\n"
        new = "a console.log(1)\nconsole.log(2)\n"
        out = self.validator.validate_edit(
            self.tenant, str(self.project.id), "src/app.py", new, prior
        )
        assert out["allowed"] is False
        assert len(out["introduced_violations"]) == 1
        assert out["pre_existing_violations_count"] == 1
        assert out["checked"] >= 1

    def test_pre_existing_only_does_not_block(self):
        prior = "a console.log(1)\nconsole.log(2)\n"
        # New content keeps the existing matches but adds nothing
        out = self.validator.validate_edit(
            self.tenant, str(self.project.id), "src/app.py", prior, prior
        )
        assert out["allowed"] is True
        assert len(out["introduced_violations"]) == 0
        assert out["pre_existing_violations_count"] == 2

    def test_removing_a_violation_does_not_block(self):
        prior = "a console.log(1)\nconsole.log(2)\n"
        new = "a\nconsole.log(2)\n"
        out = self.validator.validate_edit(
            self.tenant, str(self.project.id), "src/app.py", new, prior
        )
        assert out["allowed"] is True
        assert len(out["introduced_violations"]) == 0
        # One match survived and is still in new_content
        assert out["pre_existing_violations_count"] == 1

    def test_line_move_with_same_count_reports_zero_introduced(self):
        # Resolution A: multiset diff keyed on (kind, value, matched_substring) — line
        # moves with no net count change report zero introduced. Pin this so a future
        # diff-aware version doesn't silently regress against the spec.
        prior = "console.log(at top)\n# spam\n"
        new = "# spam\nconsole.log(at bottom)\n"
        out = self.validator.validate_edit(
            self.tenant, str(self.project.id), "src/app.py", new, prior
        )
        assert out["allowed"] is True
        assert len(out["introduced_violations"]) == 0
        assert out["pre_existing_violations_count"] == 1

    def test_new_file_attributes_all_matches_to_edit(self):
        out = self.validator.validate_edit(
            self.tenant,
            str(self.project.id),
            "src/app.py",
            "console.log(new)\n",
            prior_content=None,
        )
        assert out["allowed"] is False
        assert len(out["introduced_violations"]) == 1
        assert out["pre_existing_violations_count"] == 0

    def test_unwatched_file_skips_policy(self):
        out = self.validator.validate_edit(
            self.tenant,
            str(self.project.id),
            "README.md",
            "console.log(everywhere)\n",
            prior_content=None,
        )
        # Policy only watches src/app.py — should skip not block
        assert out["allowed"] is True
        assert out["skipped"] >= 1
        assert len(out["introduced_violations"]) == 0

    def test_violation_carries_policy_name_and_value(self):
        out = self.validator.validate_edit(
            self.tenant,
            str(self.project.id),
            "src/app.py",
            "console.log(x)\n",
            prior_content=None,
        )
        v = out["introduced_violations"][0]
        assert v["policy"] == "no-console-log"
        assert v["kind"] == "in"
        assert v["value"] == "console.log"
        assert v["matched_substring"] == "console.log"

    def test_unknown_project_raises(self):
        import pytest
        with pytest.raises(ValueError, match="Project .* not found"):
            self.validator.validate_edit(
                self.tenant,
                "00000000-0000-0000-0000-000000000000",
                "src/app.py",
                "x",
                None,
            )

    def test_tenant_isolation(self):
        # A project from a different tenant should not be visible
        other_tenant = baker.make("app.Tenant")
        import pytest
        with pytest.raises(ValueError, match="Project .* not found"):
            self.validator.validate_edit(
                other_tenant,
                str(self.project.id),
                "src/app.py",
                "x",
                None,
            )
