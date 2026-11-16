"""What a bulk change says it did, for its toast."""
from django.test import TestCase

from app.application.bulk_edit_result import BulkEditResult

class BulkEditResultTests(TestCase):
    def test_the_summary_says_what_changed_stayed_and_was_skipped(self):
        result = BulkEditResult(done="Enabled", noun="standard", noun_plural="standards", changed=2, unchanged=1)
        result.skip("drafts can't be enabled")

        assert result.summary == "Enabled 2 standards; 1 already was. Skipped 1: drafts can't be enabled."
        assert result.level == "warning"
