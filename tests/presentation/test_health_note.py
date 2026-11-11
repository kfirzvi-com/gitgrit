"""HealthNote: why a project shows the health it does, beside its grade."""
from django.test import SimpleTestCase

from app.domain.models import CommitScore
from app.presentation.health_note import NOT_CHECKED, HealthNote
from app.presentation.no_score_note import NO_RESULT


class HealthNoteTests(SimpleTestCase):
    def test_a_project_never_checked_says_so(self):
        self.assertEqual(HealthNote.text(None), NOT_CHECKED)

    def test_no_score_says_what_is_missing(self):
        self.assertEqual(HealthNote.text(CommitScore(value=None, reason="Lint errored")), "No score: Lint errored")
        self.assertEqual(HealthNote.text(CommitScore(value=None)), f"No score: {NO_RESULT}")

    def test_a_failed_commit_names_what_failed(self):
        score = CommitScore(value=None, failed=True, reason="Pinned CI failing")
        self.assertEqual(HealthNote.text(score), "Pinned CI failing")

    def test_a_grade_says_enough_on_its_own(self):
        self.assertEqual(HealthNote.text(CommitScore(value=72)), "")
