"""Tests for the `airgap_smoketest` runtime install verifier.

Drives every failure-mode branch of the operator-facing smoke test —
TLS error, wrong service at GITLAB_URL, missing CA bundle, public-egress
leak — and confirms the command's exit-code contract (non-zero on any
failure) so install scripts can chain it safely.
"""
from io import StringIO
from unittest import mock

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError


GITLAB_URL = "https://gitlab.acme.internal"


def _run(*args, **env) -> tuple[str, bool]:
    """Run `airgap_smoketest` with the given CLI args and env. Returns
    (combined_output, ok) where ok is True iff the command exited cleanly."""
    out = StringIO()
    err = StringIO()
    raised = False
    try:
        call_command("airgap_smoketest", *args, stdout=out, stderr=err)
    except CommandError:
        raised = True
    return out.getvalue() + err.getvalue(), not raised


def _gitlab_401_response():
    resp = mock.MagicMock()
    resp.status_code = 401
    resp.headers = {"Content-Type": "application/json; charset=utf-8"}
    resp.json.return_value = {"message": "401 Unauthorized"}
    return resp


class TestGitlabUrlValidation:
    def test_fails_when_gitlab_url_unset(self, monkeypatch):
        monkeypatch.delenv("GITLAB_URL", raising=False)
        out, ok = _run()
        assert not ok
        assert "GITLAB_URL is not set" in out

    def test_fails_on_non_https_scheme(self, monkeypatch):
        # Anti-SSRF: an `http://` or `file://` GITLAB_URL would let a
        # misconfigured value probe arbitrary local services via requests.
        monkeypatch.setenv("GITLAB_URL", "http://gitlab.acme.internal")
        out, ok = _run()
        assert not ok
        assert "must use https://" in out

    def test_warns_on_public_gitlab_com(self, monkeypatch):
        monkeypatch.setenv("GITLAB_URL", "https://gitlab.com")
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        with mock.patch.object(
            requests, "get", return_value=_gitlab_401_response()
        ):
            out, _ = _run()
        assert "points at public gitlab.com" in out

    def test_no_warning_for_gitlab_lookalike_hostname(self, monkeypatch):
        # `gitlab.acme.com` contains the substring "gitlab.com" but is
        # not the public service. Hostname equality (not substring) is
        # the only way to keep this from false-positiving.
        monkeypatch.setenv("GITLAB_URL", "https://gitlab.acme.com")
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        with mock.patch.object(
            requests, "get", return_value=_gitlab_401_response()
        ):
            out, _ = _run()
        assert "points at public gitlab.com" not in out


class TestCaBundleEnv:
    def test_warns_when_unset(self, monkeypatch):
        monkeypatch.setenv("GITLAB_URL", GITLAB_URL)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        with mock.patch.object(
            requests, "get", return_value=_gitlab_401_response()
        ):
            out, _ = _run()
        assert "REQUESTS_CA_BUNDLE is not set" in out

    def test_fails_when_file_missing(self, monkeypatch):
        monkeypatch.setenv("GITLAB_URL", GITLAB_URL)
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/etc/ssl/certs/custom-ca.pem")
        with mock.patch(
            "app.management.commands.airgap_smoketest.os.path.isfile",
            return_value=False,
        ), mock.patch.object(
            requests, "get", return_value=_gitlab_401_response()
        ):
            out, ok = _run()
        assert not ok
        assert "is not readable" in out

    def test_fails_on_zero_byte_bundle(self, monkeypatch):
        monkeypatch.setenv("GITLAB_URL", GITLAB_URL)
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/etc/ssl/certs/custom-ca.pem")
        with mock.patch(
            "app.management.commands.airgap_smoketest.os.path.isfile",
            return_value=True,
        ), mock.patch(
            "app.management.commands.airgap_smoketest.os.path.getsize",
            return_value=0,
        ), mock.patch.object(
            requests, "get", return_value=_gitlab_401_response()
        ):
            out, ok = _run()
        assert not ok
        assert "zero bytes" in out


class TestGitlabReachability:
    @pytest.fixture(autouse=True)
    def _gitlab_env(self, monkeypatch):
        # Common base env every test in this class shares. Each test then
        # only sets/varies what it actually needs to exercise.
        monkeypatch.setenv("GITLAB_URL", GITLAB_URL)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    def test_passes_on_gitlab_shaped_401(self, monkeypatch):
        with mock.patch.object(
            requests, "get", return_value=_gitlab_401_response()
        ):
            out, ok = _run()
        assert ok
        assert "airgap_smoketest PASSED" in out
        assert "looks like a real GitLab" in out

    def test_fails_on_ssl_error(self, monkeypatch):
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        with mock.patch.object(
            requests,
            "get",
            side_effect=requests.exceptions.SSLError("certificate verify failed"),
        ):
            out, ok = _run()
        assert not ok
        assert "TLS handshake" in out
        assert "REQUESTS_CA_BUNDLE" in out

    def test_fails_on_connection_error(self, monkeypatch):
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        with mock.patch.object(
            requests,
            "get",
            side_effect=requests.exceptions.ConnectionError("no route to host"),
        ):
            out, ok = _run()
        assert not ok
        assert "could not connect" in out

    def test_fails_on_html_404_from_wrong_service(self, monkeypatch):
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        resp = mock.MagicMock()
        resp.status_code = 404
        resp.headers = {"Content-Type": "text/html"}
        with mock.patch.object(requests, "get", return_value=resp):
            out, ok = _run()
        assert not ok
        assert "does not look like a GitLab API" in out

    def test_fails_on_401_with_html_body(self, monkeypatch):
        # An auth-proxy login page in front of a non-GitLab service often
        # returns 401 + HTML. Without the content-type + body check we'd
        # silently pass.
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        resp = mock.MagicMock()
        resp.status_code = 401
        resp.headers = {"Content-Type": "text/html"}
        with mock.patch.object(requests, "get", return_value=resp):
            out, ok = _run()
        assert not ok
        assert "does not look like a GitLab API" in out

    def test_fails_on_401_json_without_gitlab_shape(self, monkeypatch):
        # Some other JSON-speaking service that returns 401 — e.g. a
        # fronting auth gateway returning `{"error": "no_token"}`.
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        resp = mock.MagicMock()
        resp.status_code = 401
        resp.headers = {"Content-Type": "application/json"}
        resp.json.return_value = {"error": "no_token"}
        with mock.patch.object(requests, "get", return_value=resp):
            out, ok = _run()
        assert not ok
        assert "does not look like a GitLab API" in out


class TestIsolationProbe:
    """The probe runs at TCP layer (socket.create_connection), not HTTPS.
    A customer-only REQUESTS_CA_BUNDLE makes every public TLS host raise
    SSLError, which an HTTP-layer probe mis-classifies as 'unreachable' —
    a silent false-negative on a network that's actually open. Tests below
    pin the TCP-layer probe so a future regression to requests-based code
    fails loudly here."""

    PROBE_TARGET = ("www.google.com", 443)

    def test_passes_when_internet_unreachable(self, monkeypatch):
        monkeypatch.setenv("GITLAB_URL", GITLAB_URL)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

        with mock.patch.object(requests, "get", return_value=_gitlab_401_response()), \
             mock.patch(
                 "app.management.commands.airgap_smoketest.socket.create_connection",
                 side_effect=OSError("no route to host"),
             ) as m_sock:
            out, ok = _run("--check-isolation")

        assert ok
        assert "public internet appears blocked" in out
        # Pin: probe MUST target the public host at port 443.
        m_sock.assert_called_once()
        assert m_sock.call_args.args[0] == self.PROBE_TARGET

    def test_fails_when_internet_reachable(self, monkeypatch):
        # If www.google.com:443 accepts a TCP connection from the container,
        # the network is not actually closed and the customer is *not*
        # air-gapped — the smoke test must catch this.
        monkeypatch.setenv("GITLAB_URL", GITLAB_URL)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

        fake_sock = mock.MagicMock()
        # Context-manager protocol: socket.create_connection's return value
        # is entered via `with`. The MagicMock satisfies that by default.
        with mock.patch.object(requests, "get", return_value=_gitlab_401_response()), \
             mock.patch(
                 "app.management.commands.airgap_smoketest.socket.create_connection",
                 return_value=fake_sock,
             ):
            out, ok = _run("--check-isolation")

        assert not ok
        assert "public internet is reachable" in out
        assert "NOT an air-gapped install" in out

    def test_probe_uses_tcp_not_https(self, monkeypatch):
        # Regression guard: a previous version of the probe used
        # requests.get(), which silently false-negatived under the
        # customer-CA bundle (SSLError == 'blocked'). The probe MUST NOT
        # send an HTTPS request to the probe target.
        monkeypatch.setenv("GITLAB_URL", GITLAB_URL)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

        def _requests_get(url, **kwargs):
            # Make any accidental HTTPS probe to google.com a test failure.
            assert "google.com" not in url, (
                "isolation probe must use TCP socket, not requests.get()"
            )
            return _gitlab_401_response()

        with mock.patch.object(requests, "get", side_effect=_requests_get), \
             mock.patch(
                 "app.management.commands.airgap_smoketest.socket.create_connection",
                 side_effect=OSError("no route to host"),
             ) as m_sock:
            _run("--check-isolation")

        # Pin: the probe must have gone through the socket path. A regression
        # that quietly dropped the probe would otherwise slip past this guard.
        m_sock.assert_called_once()
