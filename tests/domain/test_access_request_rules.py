"""An access request reaches superusers only once its email is confirmed;
with the onboarding form on, once the form is in too."""
from unittest import TestCase

from app.domain.models import AccessRequest, User


def _request(**fields):
    return AccessRequest(user=User(email="ada@example.com"), **fields)


class ReadyForReviewTests(TestCase):
    def test_unconfirmed_is_never_ready(self):
        request = _request()
        self.assertFalse(request.is_ready_for_review(form_required=False))
        self.assertFalse(request.is_ready_for_review(form_required=True))

    def test_confirmed_is_ready_without_the_form(self):
        request = _request()
        request.confirm_email()
        self.assertTrue(request.is_ready_for_review(form_required=False))
        self.assertFalse(request.is_ready_for_review(form_required=True))

    def test_confirmed_and_submitted_is_ready_with_the_form(self):
        request = _request()
        request.confirm_email()
        request.submit({"name": "Ada"})
        self.assertTrue(request.is_ready_for_review(form_required=True))

    def test_a_reviewed_request_is_not_waiting(self):
        request = _request()
        request.confirm_email()
        request.reject(User(email="root@example.com"))
        self.assertFalse(request.is_ready_for_review(form_required=False))

    def test_confirming_counts_once(self):
        request = _request()
        self.assertTrue(request.confirm_email())
        first = request.email_confirmed_at
        self.assertFalse(request.confirm_email())
        self.assertEqual(request.email_confirmed_at, first)


class ReviewTests(TestCase):
    def test_an_unconfirmed_request_cannot_be_reviewed(self):
        for review in ("approve", "reject"):
            request = _request()
            with self.subTest(review=review), self.assertRaises(ValueError):
                getattr(request, review)(User(email="root@example.com"))
            self.assertTrue(request.is_pending)
