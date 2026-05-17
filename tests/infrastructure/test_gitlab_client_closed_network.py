"""Closed-network connectivity check for the GitLab platform client.

The whole point of an air-gap install is that the operator can connect
GitGrit to *their* self-hosted GitLab without GitGrit ever reaching out
to gitlab.com or anywhere else on the public internet. This test pins
that property at the platform-client layer.

It does NOT spin up a real TLS server — `requests` is intercepted at the
module level and any host other than the operator-supplied internal
GitLab raises immediately, so a regression that points the client at
gitlab.com (e.g. a hardcoded URL, a redirect followed blindly, a stray
`verify=False`) fails the test by name.
"""
from unittest import mock
from urllib.parse import urlparse

import pytest

from app.domain.models import Platform, PlatformConnection
from app.infrastructure.platform_client import GitLabClient

INTERNAL_GITLAB = "https://gitlab.acme.internal"
INTERNAL_HOST = urlparse(INTERNAL_GITLAB).hostname
FAKE_TOKEN = "glpat-fake-token"


def _internal_gitlab_connection():
    """A `PlatformConnection` doesn't need a DB row for this check — the
    client only reads .base_url, .access_token, .platform off the instance."""
    conn = mock.MagicMock(spec=PlatformConnection)
    conn.platform = Platform.GITLAB
    conn.base_url = INTERNAL_GITLAB
    conn.access_token = FAKE_TOKEN
    return conn


def _make_response(payload):
    resp = mock.MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _payload_for_get(url: str):
    """Return a `requests.Response.json()` shape that matches what the
    real GitLab API would return for the given URL, so the client's
    response-parsing code doesn't crash inside the test."""
    path = urlparse(url).path
    if path.endswith("/languages"):
        return {"Python": 12345, "JavaScript": 6789}
    if path.endswith("/hooks") or path.endswith("/projects"):
        return []
    if "/projects/" in path:
        # /projects/<id> — used by get_topics; everything else ignores the body.
        return {"id": 42, "topics": ["acme", "infra"]}
    # /user (test_token) — body unused, code only checks status_code.
    return {}


@pytest.fixture
def closed_network():
    """Replace `app.infrastructure.platform_client.requests` so any HTTP
    call to a host other than INTERNAL_HOST raises a closed-network
    violation. Yields (seen_urls, fake_requests_module)."""
    seen_urls: list[str] = []

    def _guard(payload_fn):
        def _fn(url, **kwargs):
            seen_urls.append(url)
            host = urlparse(url).hostname
            if host != INTERNAL_HOST:
                raise AssertionError(
                    f"Closed-network violation: GitLabClient tried to reach "
                    f"'{host}' (URL: {url}). Only '{INTERNAL_HOST}' is "
                    f"reachable in the operator's network."
                )
            return _make_response(payload_fn(url))
        return _fn

    with mock.patch(
        "app.infrastructure.platform_client.requests"
    ) as fake_req:
        fake_req.get.side_effect = _guard(_payload_for_get)
        fake_req.post.side_effect = _guard(lambda _url: {"id": 999})
        fake_req.delete.side_effect = _guard(lambda _url: None)
        yield seen_urls, fake_req


class TestGitLabClientStaysInsideClosedNetwork:
    """Every public method on GitLabClient must only ever hit the
    operator's base_url, never gitlab.com or anything else."""

    def test_test_token_only_hits_internal_gitlab(self, closed_network):
        seen_urls, _ = closed_network

        client = GitLabClient(_internal_gitlab_connection())
        client.test_token()

        assert seen_urls == [f"{INTERNAL_GITLAB}/api/v4/user"]

    def test_search_projects_only_hits_internal_gitlab(self, closed_network):
        seen_urls, _ = closed_network

        client = GitLabClient(_internal_gitlab_connection())
        client.search_projects(query="acme")

        assert len(seen_urls) == 1
        assert seen_urls[0].startswith(f"{INTERNAL_GITLAB}/api/v4/projects")

    def test_get_languages_only_hits_internal_gitlab(self, closed_network):
        seen_urls, _ = closed_network

        client = GitLabClient(_internal_gitlab_connection())
        client.get_languages(external_id="42")

        assert seen_urls == [f"{INTERNAL_GITLAB}/api/v4/projects/42/languages"]

    def test_get_topics_only_hits_internal_gitlab(self, closed_network):
        seen_urls, _ = closed_network

        client = GitLabClient(_internal_gitlab_connection())
        client.get_topics(external_id="42")

        assert seen_urls == [f"{INTERNAL_GITLAB}/api/v4/projects/42"]

    def test_create_webhook_only_hits_internal_gitlab(self, closed_network):
        # GitLab's create_webhook is single-request (POST). GitHub's version
        # does GET+POST; don't "fix" this to match.
        seen_urls, _ = closed_network

        client = GitLabClient(_internal_gitlab_connection())
        client.create_webhook(
            external_id="42",
            target_url="https://gitgrit.acme.internal/api/webhooks/gitlab/",
            secret="s3cret",
        )

        assert seen_urls == [f"{INTERNAL_GITLAB}/api/v4/projects/42/hooks"]

    def test_delete_webhook_only_hits_internal_gitlab(self, closed_network):
        seen_urls, _ = closed_network

        client = GitLabClient(_internal_gitlab_connection())
        client.delete_webhook(external_id="42", webhook_id="99")

        assert seen_urls == [f"{INTERNAL_GITLAB}/api/v4/projects/42/hooks/99"]


class TestGitLabClientAuthAndTls:
    """Auth header + TLS behavior — the parts that determine whether
    requests against the operator's internal GitLab actually succeed."""

    def test_uses_private_token_header(self, closed_network):
        _, fake_req = closed_network

        client = GitLabClient(_internal_gitlab_connection())
        client.test_token()

        sent_headers = fake_req.get.call_args.kwargs["headers"]
        assert sent_headers["PRIVATE-TOKEN"] == FAKE_TOKEN

    def test_never_passes_verify_false(self, closed_network):
        """A common mistake when self-signed certs cause errors is to set
        `verify=False`. Air-gap deployments must instead rely on the
        operator CA chain — propagated into the sandbox via SSL_CERT_FILE
        (which `requests` honors as a fallback when REQUESTS_CA_BUNDLE is
        unset) — so TLS verification stays intact across the wire."""
        _, fake_req = closed_network

        client = GitLabClient(_internal_gitlab_connection())
        client.test_token()
        client.search_projects()
        client.create_webhook(external_id="42", target_url="x", secret="y")

        all_calls = (
            fake_req.get.call_args_list
            + fake_req.post.call_args_list
            + fake_req.delete.call_args_list
        )
        for call in all_calls:
            assert call.kwargs.get("verify") is not False, (
                f"GitLabClient passed verify=False to {call.args[0]} — "
                f"this bypasses the operator CA chain and breaks the "
                f"air-gap TLS guarantee."
            )
