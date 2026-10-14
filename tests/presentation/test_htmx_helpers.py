import json
from unittest import TestCase

from django.http import HttpResponse

from app.presentation.htmx import toast


class ToastTests(TestCase):
    def test_sets_the_toast_trigger(self):
        response = toast(HttpResponse(), "Saved.")
        assert json.loads(response["HX-Trigger"]) == {"toast": {"level": "success", "text": "Saved."}}

    def test_keeps_triggers_already_set(self):
        response = HttpResponse()
        response["HX-Trigger"] = "countChanged"
        toast(response, "Nope.", "error")
        assert json.loads(response["HX-Trigger"]) == {
            "countChanged": None,
            "toast": {"level": "error", "text": "Nope."},
        }
