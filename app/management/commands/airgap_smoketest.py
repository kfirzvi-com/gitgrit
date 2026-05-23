"""Runtime smoke test for an air-gapped GitGrit install.

Operator-facing: run after `airgap_setup` to confirm the live container
can actually talk to the operator's GitLab over the operator's CA chain.

    docker compose -f docker-compose.prod.yml exec app \\
        python manage.py airgap_smoketest

    docker compose -f docker-compose.prod.yml exec app \\
        python manage.py airgap_smoketest --check-isolation

What it verifies:
  * `GITLAB_URL` is set (and is not the public gitlab.com — warn only).
  * `REQUESTS_CA_BUNDLE` points at a readable non-empty PEM.
  * The app container can resolve, connect, and complete TLS to
    `GITLAB_URL`, and the endpoint behaves like a GitLab instance.
  * `--check-isolation`: the container has no egress to the public
    internet (probes a known public host that should be unreachable).

Exit code is non-zero on failure so operators can wire this into an
install / health-check script.
"""
import os
import socket
from urllib.parse import urlparse

import requests
from django.core.management.base import BaseCommand, CommandError

# Tried by --check-isolation to prove the host has no public egress.
# Probed at TCP layer (not HTTPS) so a customer-only REQUESTS_CA_BUNDLE
# can't mask a reachable network with an SSLError — see _check_no_public_egress.
ISOLATION_PROBE_HOST = "www.google.com"
ISOLATION_PROBE_PORT = 443


class Command(BaseCommand):
    help = "Verify the air-gap install can reach the customer's GitLab over TLS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check-isolation",
            action="store_true",
            help=(
                "Also verify the container CANNOT reach the public internet. "
                "Probes a known public host; a successful request fails the "
                "smoke test because it means the network isn't actually closed."
            ),
        )

    def handle(self, *args, **opts):
        all_ok = True
        all_ok &= self._check_gitlab_url_set()
        all_ok &= self._check_ca_bundle_env()
        all_ok &= self._check_gitlab_reachable()
        if opts["check_isolation"]:
            all_ok &= self._check_no_public_egress()
        if not all_ok:
            # Non-zero exit so this can be chained in install scripts.
            raise CommandError("airgap_smoketest FAILED — see lines marked FAIL above.")
        self.stdout.write(self.style.SUCCESS("airgap_smoketest PASSED"))

    def _ok(self, msg: str) -> None:
        self.stdout.write(self.style.SUCCESS(f"OK    {msg}"))

    def _warn(self, msg: str) -> None:
        self.stdout.write(self.style.WARNING(f"WARN  {msg}"))

    def _fail(self, msg: str) -> None:
        self.stdout.write(self.style.ERROR(f"FAIL  {msg}"))

    def _check_gitlab_url_set(self) -> bool:
        url = os.environ.get("GITLAB_URL", "")
        if not url:
            self._fail("GITLAB_URL is not set in the container environment")
            return False
        parsed = urlparse(url)
        # Reject non-https schemes outright. `file://`, `gopher://`, etc.
        # would let a misconfigured GITLAB_URL probe arbitrary local services
        # via `requests`. We need TLS anyway, so plain http is also rejected.
        if parsed.scheme != "https":
            self._fail(
                f"GITLAB_URL='{url}' must use https:// — got '{parsed.scheme}://'"
            )
            return False
        # Hostname equality (not substring) so we don't false-positive on
        # legitimate internal names like `gitlab.acme.com`.
        if parsed.hostname == "gitlab.com":
            self._warn(
                f"GITLAB_URL='{url}' points at public gitlab.com — air-gap "
                "installs usually point at an internal hostname"
            )
        self._ok(f"GITLAB_URL={url}")
        return True

    def _check_ca_bundle_env(self) -> bool:
        bundle = os.environ.get("REQUESTS_CA_BUNDLE", "")
        if not bundle:
            # Not a hard fail: the operator might use a system trust store
            # that already includes their CA. But it's the documented air-gap
            # setup, so flag the deviation.
            self._warn(
                "REQUESTS_CA_BUNDLE is not set — TLS will fall back to the "
                "container's default trust store, which usually does not "
                "include your operator CA"
            )
            return True
        if not os.path.isfile(bundle):
            self._fail(
                f"REQUESTS_CA_BUNDLE={bundle} but the file is not readable "
                "from inside the container"
            )
            return False
        size = os.path.getsize(bundle)
        if size == 0:
            self._fail(f"{bundle} is zero bytes — check the host-side file")
            return False
        self._ok(f"REQUESTS_CA_BUNDLE={bundle} ({size} bytes)")
        return True

    def _check_gitlab_reachable(self) -> bool:
        url = os.environ.get("GITLAB_URL", "").rstrip("/")
        if not url:
            return False
        # /api/v4/version always requires authentication, so an unauthenticated
        # probe gets a clean 401 with a GitLab-shaped JSON body. Earlier
        # versions of this check hit /api/v4/projects, which on a default
        # GitLab CE install returns 200 with `[]` when no public projects
        # exist — that pattern would false-fail the smoketest on a freshly
        # provisioned customer GitLab.
        target = f"{url}/api/v4/version"
        try:
            # `allow_redirects=False` so a reverse-proxy or SSO bouncing us
            # to a login page doesn't mask a misconfigured GITLAB_URL — we
            # want the API to answer directly, not via a redirect chain.
            resp = requests.get(target, timeout=10, allow_redirects=False)
        except requests.exceptions.SSLError as exc:
            self._fail(
                f"TLS handshake to {url} failed: {exc}. Make sure "
                "REQUESTS_CA_BUNDLE points at the CA chain that signed "
                "your GitLab's cert (not the server cert itself)."
            )
            return False
        except requests.exceptions.ConnectionError as exc:
            self._fail(
                f"could not connect to {url}: {exc}. Check DNS, routing, "
                "and that the app container is on a network that can "
                "reach your internal GitLab."
            )
            return False
        except requests.exceptions.RequestException as exc:
            self._fail(f"request to {url} failed: {exc}")
            return False

        # /api/v4/version without a token returns 401 with a JSON body
        # `{"message": "401 Unauthorized"}`. Anything else (HTML login
        # page, 200, 5xx, 302) means we're hitting the wrong service.
        # We also peek into the body so an unrelated upstream JSON 401
        # (e.g. a fronting auth proxy) doesn't pass.
        if resp.status_code == 401:
            content_type = resp.headers.get("Content-Type", "")
            if "json" in content_type.lower():
                try:
                    body = resp.json()
                except ValueError:
                    body = {}
                message = str(body.get("message", "")).lower()
                if "unauthorized" in message or "401" in message:
                    self._ok(
                        f"{target} returned 401 JSON with GitLab-shaped body "
                        "— looks like a real GitLab"
                    )
                    return True
        self._fail(
            f"{target} returned HTTP {resp.status_code} "
            f"(Content-Type: {resp.headers.get('Content-Type', '?')}) — "
            "does not look like a GitLab API. Wrong GITLAB_URL?"
        )
        return False

    def _check_no_public_egress(self) -> bool:
        # TCP-layer probe, not HTTPS: in a real air-gap install
        # REQUESTS_CA_BUNDLE is set to a customer-only CA that won't sign
        # any public site's cert, so an HTTPS probe would raise SSLError
        # and be misread as "unreachable" — a silent false negative on
        # a network that's actually open. socket.create_connection bypasses
        # TLS entirely and only succeeds when the L4 path really works.
        target = f"{ISOLATION_PROBE_HOST}:{ISOLATION_PROBE_PORT}"
        try:
            with socket.create_connection(
                (ISOLATION_PROBE_HOST, ISOLATION_PROBE_PORT), timeout=3
            ):
                pass
        except OSError:
            # gaierror (DNS fail) and timeout/refused both subclass OSError.
            self._ok(f"public internet appears blocked ({target} is unreachable)")
            return True
        self._fail(
            f"public internet is reachable: TCP {target} accepted a "
            "connection. This is NOT an air-gapped install."
        )
        return False
