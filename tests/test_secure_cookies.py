"""Session and CSRF cookies are sent only over https (SOC 2 CC6.1, CC6.7)."""
from django.conf import settings
from django.test import TestCase, tag


@tag("security")
class SecureCookieTests(TestCase):
    def test_both_cookies_are_marked_secure(self):
        assert settings.SESSION_COOKIE_SECURE is True
        assert settings.CSRF_COOKIE_SECURE is True

    def test_csrf_cookie_is_sent_with_the_secure_flag(self):
        response = self.client.get("/accounts/login/")
        assert response.cookies["csrftoken"]["secure"] is True
