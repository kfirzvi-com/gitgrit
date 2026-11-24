"""GitHubApi's caching and rate-limit care: unchanged answers come from the
cache through a conditional request, and a token low on allowance stops
syncing until the reset."""
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.core.cache.backends.locmem import LocMemCache
from django.test import SimpleTestCase

from app.application.delivery import RateLimited, SourceUnavailable
from app.infrastructure.delivery.github_api import GitHubApi

NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
RESET = int((NOW + timedelta(minutes=30)).timestamp())


def answer(status=200, body=None, etag='"v1"', remaining=4000, limit=5000, links=None):
    response = mock.Mock(status_code=status, links=links or {})
    response.json.return_value = body
    response.headers = {"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": str(remaining), "X-RateLimit-Reset": str(RESET)}
    if etag:
        response.headers["ETag"] = etag
    response.raise_for_status = mock.Mock()
    return response


class GitHubApiTests(SimpleTestCase):
    def setUp(self):
        self.cache = LocMemCache("test-github-api", {})
        self.cache.clear()

    def api(self, token="t1"):
        return GitHubApi("https://api.github.com", token, "acme/shop", cache=self.cache, now=lambda: NOW)

    def test_an_unchanged_answer_comes_from_the_cache_through_a_conditional_request(self):
        with mock.patch("requests.get", side_effect=[answer(body={"n": 1}), answer(status=304, body=None)]) as get:
            first = self.api().get("pulls/1")
            second = self.api().get("pulls/1")

        self.assertEqual(first, second)
        self.assertEqual(get.call_args_list[1].kwargs["headers"]["If-None-Match"], '"v1"')

    def test_tokens_do_not_share_cached_answers(self):
        with mock.patch("requests.get", side_effect=[answer(body={"n": 1}), answer(body={"n": 2})]) as get:
            self.api("t1").get("pulls/1")
            self.assertEqual(self.api("t2").get("pulls/1"), {"n": 2})

        self.assertNotIn("If-None-Match", get.call_args_list[1].kwargs["headers"])

    def test_pages_cache_items_slimmed_and_follow_next_links(self):
        pages = [
            answer(body=[{"id": 1, "big": "x" * 100}], links={"next": {"url": "https://api.github.com/page2"}}),
            answer(body=[{"id": 2, "big": "y"}], etag='"v2"'),
        ]
        with mock.patch("requests.get", side_effect=pages):
            items = list(self.api().pages("pulls", slim=lambda item: {"id": item["id"]}))

        self.assertEqual(items, [{"id": 1}, {"id": 2}])

    def test_a_token_low_on_allowance_stops_until_the_reset(self):
        with mock.patch("requests.get", return_value=answer(body={}, remaining=400)) as get:
            self.api().get("a")
            with self.assertRaises(RateLimited) as raised:
                self.api().get("b")

        self.assertEqual(get.call_count, 1)
        self.assertEqual(raised.exception.resets_at, NOW + timedelta(minutes=30))

    def test_an_exhausted_allowance_is_rate_limited_not_a_missing_permission(self):
        with mock.patch("requests.get", return_value=answer(status=403, remaining=0)):
            with self.assertRaises(RateLimited):
                self.api().get("deployments")

    def test_a_refusal_names_the_permission_to_grant(self):
        with mock.patch("requests.get", return_value=answer(status=403)):
            with self.assertRaisesMessage(SourceUnavailable, "give it Deployments read access"):
                self.api().get("deployments", permission="Deployments")
