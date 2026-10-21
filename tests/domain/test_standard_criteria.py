from django.test import SimpleTestCase

from app.domain.standard_criteria import language_matches


class TestLanguageMatches(SimpleTestCase):
    def test_empty_standard_languages_matches_every_project(self):
        self.assertIs(language_matches([], ["python", "go"]), True)
        self.assertIs(language_matches([], []), True)

    def test_matches_when_any_language_overlaps(self):
        self.assertIs(language_matches(["python"], ["Python", "YAML"]), True)

    def test_is_case_insensitive(self):
        self.assertIs(language_matches(["Python"], ["python"]), True)
        self.assertIs(language_matches(["PYTHON"], ["python"]), True)

    def test_no_overlap_returns_false(self):
        self.assertIs(language_matches(["rust"], ["python", "go"]), False)

    def test_empty_project_languages_with_non_empty_standard_returns_false(self):
        self.assertIs(language_matches(["python"], []), False)


class AppliesTests(SimpleTestCase):
    def test_event_branch_filter_and_languages_must_all_match(self):
        from app.domain.standard_criteria import applies

        criteria = {"events": ["push"], "ref": "^main$", "languages": ["Python"]}

        assert applies(criteria, project_languages=["python"], event_type="push", ref="refs/heads/main")
        assert not applies(criteria, project_languages=["python"], event_type="tag", ref="main")
        assert not applies(criteria, project_languages=["python"], event_type="push", ref="dev")
        assert not applies(criteria, project_languages=["Go"], event_type="push", ref="main")
        assert applies(criteria, project_languages=["Python"], ref="main", skip_event_check=True)
        # A pull request matches its target branch.
        assert applies(criteria, project_languages=["Python"], event_type="push", ref="dev", target_ref="main")
