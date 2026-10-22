"""A commit's runs on the Results tab, worst first: running, then failed
(Required first, lowest score first), then could not run (never "failed"),
then passed; each run grouped by the importance it ran with."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from app.presentation.commit_results import CommitResultGrouping


def run(name, status, score=0, importance="major"):
    return SimpleNamespace(standard_name=name, status=status, score=score, importance=importance)


class CommitResultGroupingTests(SimpleTestCase):
    def test_worst_first_and_by_importance_within_each_group(self):
        groups = CommitResultGrouping.of(
            [
                run("Readme", "passed", 100, importance="minor"),
                run("Pinned", "passed", 100),
                run("Linter", "failed", 40),
                run("Typos", "failed", 0, importance="minor"),
                run("License", "error", 0),
                run("No secrets", "failed", 90, importance="required"),
                run("Changelog", "failed", 10),
                run("Docs", "running"),
            ]
        )

        assert [(g.key, [r.standard_name for r in g.runs]) for g in groups] == [
            ("running", ["Docs"]),
            # Required, then Major (lowest score first), then Minor.
            ("failed", ["No secrets", "Changelog", "Linter", "Typos"]),
            ("errored", ["License"]),
            ("passed", ["Pinned", "Readme"]),
        ]

    def test_empty_groups_are_left_out(self):
        assert [g.key for g in CommitResultGrouping.of([run("Readme", "passed", 100)])] == ["passed"]
