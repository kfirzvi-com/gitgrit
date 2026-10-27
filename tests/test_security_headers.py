"""Transport and browser security headers (SOC 2 CC6.1, CC6.7).

HTTPS-only settings follow the scheme of SITE_URL, so a self-hosted install
served over plain http keeps working without extra config, while
app.gitgrit.dev gets HSTS, an https redirect and Secure cookies. Every page
also carries a Content-Security-Policy, a Permissions-Policy and a strict
Referrer-Policy.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings, tag

from django.utils.csp import CSP

from gitgrit.middleware import PermissionsPolicyMiddleware

BASE_DIR = Path(settings.BASE_DIR)

_DUMP = """
import json
from gitgrit import settings as s
print(json.dumps({
    "hsts": [s.SECURE_HSTS_SECONDS, s.SECURE_HSTS_INCLUDE_SUBDOMAINS,
             getattr(s, "SECURE_HSTS_PRELOAD", False)],
    "ssl_redirect": s.SECURE_SSL_REDIRECT,
    "cookies_secure": [s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE],
    "cookies_httponly": [s.SESSION_COOKIE_HTTPONLY, s.CSRF_COOKIE_HTTPONLY],
}))
"""


def _settings_with(**env):
    """Import gitgrit.settings in a fresh interpreter: a minimal production
    environment plus ``env``."""
    clean = {
        k: v for k, v in os.environ.items()
        if not k.startswith(("DEBUG", "SITE_URL", "HTTPS_ONLY", "DJANGO_SETTINGS"))
    }
    clean.update({"DEBUG": "False", "SECRET_KEY": "x" * 50, **env})
    out = subprocess.run(
        [sys.executable, "-c", _DUMP], cwd=BASE_DIR, env=clean,
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


@tag("security")
class HttpsOnlySettingsTests(SimpleTestCase):
    def test_https_site_gets_hsts_redirect_and_secure_cookies(self):
        s = _settings_with(SITE_URL="https://app.gitgrit.dev")
        assert s["hsts"] == [31536000, True, False]
        assert s["ssl_redirect"] is True
        assert s["cookies_secure"] == [True, True]

    def test_plain_http_self_host_keeps_working(self):
        s = _settings_with(SITE_URL="http://gitgrit.internal:3000")
        assert s["hsts"][0] == 0
        assert s["ssl_redirect"] is False
        assert s["cookies_secure"] == [False, False]

    def test_debug_never_forces_https(self):
        s = _settings_with(DEBUG="True", SITE_URL="https://app.gitgrit.dev")
        assert s["ssl_redirect"] is False
        assert s["cookies_secure"] == [False, False]

    def test_operator_can_override_either_way(self):
        assert _settings_with(SITE_URL="https://x.example", HTTPS_ONLY="False")["ssl_redirect"] is False
        assert _settings_with(SITE_URL="http://x.example", HTTPS_ONLY="True")["ssl_redirect"] is True
        assert _settings_with(SITE_URL="https://x.example", HTTPS_ONLY="")["ssl_redirect"] is True

    def test_cookies_are_never_readable_by_script(self):
        assert _settings_with(SITE_URL="http://x.example")["cookies_httponly"] == [True, True]


@tag("security")
class MiddlewareOrderTests(SimpleTestCase):
    def test_health_check_runs_before_the_https_redirect(self):
        # kamal-proxy probes /up/ over plain http; SecurityMiddleware would
        # redirect it to https and fail the deploy.
        mw = settings.MIDDLEWARE
        assert mw.index("gitgrit.middleware.HealthCheckMiddleware") < mw.index(
            "django.middleware.security.SecurityMiddleware"
        )


@tag("security")
@override_settings(SECURE_SSL_REDIRECT=True)
class HttpsRedirectTests(TestCase):
    def test_kamal_health_probe_over_plain_http_is_not_redirected(self):
        response = self.client.get("/up/", HTTP_HOST="gitgrit-web-abc123")
        assert response.status_code == 200

    def test_plain_http_page_redirects_to_https(self):
        response = self.client.get("/accounts/login/")
        assert response.status_code == 301
        assert response["Location"].startswith("https://")

    def test_request_marked_https_by_the_proxy_is_served(self):
        response = self.client.get("/accounts/login/", HTTP_X_FORWARDED_PROTO="https")
        assert response.status_code == 200


@tag("security")
class ResponseHeaderTests(TestCase):
    def setUp(self):
        self.response = self.client.get("/accounts/login/")

    def test_page_renders(self):
        assert self.response.status_code == 200

    def test_csp_is_enforced_and_blocks_framing_and_plugins(self):
        csp = self.response["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp
        assert "base-uri 'self'" in csp

    def test_strict_csp_runs_in_report_only_mode(self):
        report_only = self.response["Content-Security-Policy-Report-Only"]
        script_src = re.search(r"script-src ([^;]+)", report_only).group(1)
        assert "'unsafe-inline'" not in script_src
        assert "'unsafe-eval'" not in script_src
        # Django writes the nonce into the header only on pages that use
        # {{ csp_nonce }}, so check the policy itself asks for one.
        assert CSP.NONCE in settings.SECURE_CSP_REPORT_ONLY["script-src"]

    def test_permissions_policy_denies_unused_browser_features(self):
        policy = self.response["Permissions-Policy"]
        assert settings.PERMISSIONS_POLICY
        for feature in settings.PERMISSIONS_POLICY:
            assert f"{feature}=()" in policy

    def test_api_docs_page_is_served_under_the_policy(self):
        # Swagger UI loads its bundle from jsdelivr with an inline bootstrap script.
        response = self.client.get("/api/v1/docs/")
        assert response.status_code == 200
        assert "https://cdn.jsdelivr.net" in response["Content-Security-Policy"]

    def test_referrer_and_framing_headers(self):
        assert self.response["Referrer-Policy"] == "same-origin"
        assert self.response["X-Frame-Options"] == "DENY"
        assert self.response["X-Content-Type-Options"] == "nosniff"


@tag("security")
class CSPCoversTemplateAssetsTests(SimpleTestCase):
    """Every outside host the templates load from is in both policies, so the
    enforced CSP never breaks a page and the report-only one stays honest."""

    def _hosts(self, tag, attr, must_have=""):
        """Hosts of absolute URLs in ``attr`` of every ``<tag>`` (attributes in
        any order) whose text contains ``must_have``."""
        hosts = set()
        for path in (BASE_DIR / "app" / "templates").rglob("*.html"):
            for element in re.findall(rf"<{tag}\b[^>]*>", path.read_text()):
                url = re.search(rf'\b{attr}="(https://[^"]+)"', element)
                if url and must_have in element:
                    hosts.add(re.match(r"https://[^/]+", url.group(1)).group(0))
        return hosts

    def test_every_external_script_host_is_allowed(self):
        hosts = self._hosts("script", "src")
        assert hosts
        for policy in (settings.SECURE_CSP, settings.SECURE_CSP_REPORT_ONLY):
            assert hosts <= set(policy["script-src"]), hosts - set(policy["script-src"])

    def test_every_external_stylesheet_host_is_allowed(self):
        hosts = self._hosts("link", "href", must_have='rel="stylesheet"')
        assert hosts
        for policy in (settings.SECURE_CSP, settings.SECURE_CSP_REPORT_ONLY):
            assert hosts <= set(policy["style-src"]), hosts - set(policy["style-src"])

    def test_google_fonts_files_are_allowed(self):
        # fonts.googleapis.com serves CSS that pulls the files from gstatic.
        if self._hosts("link", "href", must_have="fonts.googleapis.com"):
            for policy in (settings.SECURE_CSP, settings.SECURE_CSP_REPORT_ONLY):
                assert "https://fonts.gstatic.com" in policy["font-src"]


@tag("security")
class PermissionsPolicyHeaderTests(SimpleTestCase):
    def test_tokens_pass_through_and_origins_are_quoted(self):
        header = PermissionsPolicyMiddleware.build(
            {"camera": [], "fullscreen": ["self", "https://x.example"], "usb": ["*"]}
        )
        assert header == 'camera=(), fullscreen=(self "https://x.example"), usb=(*)'

    def test_header_follows_the_current_setting(self):
        middleware = PermissionsPolicyMiddleware(lambda request: HttpResponse())
        with override_settings(PERMISSIONS_POLICY={"camera": ["self"]}):
            response = middleware(RequestFactory().get("/"))
        assert response["Permissions-Policy"] == "camera=(self)"
