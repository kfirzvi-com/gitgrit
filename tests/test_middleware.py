"""TenantMiddleware resolves the active workspace from the session.

The session's ``active_tenant_id`` is only trusted when a Membership backs it;
otherwise the user falls back to their oldest own workspace. A superuser in
the support view (a timestamp in the session, set by switch_tenant) is the one
exception: the id is resolved directly, the request is flagged, and writes
are logged. The support view lasts until the user switches back or logs in
again; it never survives a login.
"""
import logging
import uuid
from datetime import timedelta

import pytest
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from app.workspace_access import ACTIVE_TENANT_KEY, SUPPORT_VIEW_STARTED_KEY


def _login(client, superuser=False, tenant_name="Home"):
    user = baker.make("app.User", is_superuser=superuser)
    tenant = baker.make("app.Tenant", name=tenant_name, slug=tenant_name.lower())
    baker.make("app.Membership", user=user, tenant=tenant, role="owner")
    client.force_login(user)
    _set_session(client, {ACTIVE_TENANT_KEY: str(tenant.id)})
    return user, tenant


def _set_session(client, values):
    session = client.session
    for key, value in values.items():
        if value is None:
            session.pop(key, None)
        else:
            session[key] = value
    session.save()


def _enter_support(client, tenant, started=None):
    started = started or timezone.now()
    _set_session(
        client,
        {
            ACTIVE_TENANT_KEY: str(tenant.id),
            SUPPORT_VIEW_STARTED_KEY: started.isoformat(),
        },
    )


@pytest.mark.django_db
class TestTenantMiddlewareForMembers(TestCase):
    def test_active_tenant_from_session_when_member(self):
        user, home = _login(self.client)
        other = baker.make("app.Tenant", name="Other", slug="other")
        baker.make("app.Membership", user=user, tenant=other)
        _set_session(self.client, {ACTIVE_TENANT_KEY: str(other.id)})

        response = self.client.get(reverse("dashboard"))

        assert response.wsgi_request.tenant == other
        assert response.wsgi_request.tenant_is_support_view is False

    def test_foreign_id_falls_back_to_own_workspace(self):
        _, home = _login(self.client)
        foreign = baker.make("app.Tenant", name="Foreign", slug="foreign")
        _set_session(self.client, {ACTIVE_TENANT_KEY: str(foreign.id)})

        response = self.client.get(reverse("dashboard"))

        assert response.wsgi_request.tenant == home
        assert response.wsgi_request.tenant_is_support_view is False
        assert self.client.session[ACTIVE_TENANT_KEY] == str(home.id)

    def test_support_timestamp_does_not_help_a_non_superuser(self):
        _, home = _login(self.client, superuser=False)
        foreign = baker.make("app.Tenant", name="Foreign", slug="foreign")
        _enter_support(self.client, foreign)

        response = self.client.get(reverse("dashboard"))

        assert response.wsgi_request.tenant == home
        assert response.wsgi_request.tenant_is_support_view is False
        assert SUPPORT_VIEW_STARTED_KEY not in self.client.session

    def test_malformed_id_is_dropped_not_raised(self):
        _, home = _login(self.client)
        _set_session(self.client, {ACTIVE_TENANT_KEY: "not-a-uuid"})

        response = self.client.get(reverse("dashboard"))

        assert response.status_code == 200
        assert response.wsgi_request.tenant == home
        assert self.client.session[ACTIVE_TENANT_KEY] == str(home.id)

    def test_deleted_workspace_falls_back(self):
        _, home = _login(self.client)
        _set_session(self.client, {ACTIVE_TENANT_KEY: str(uuid.uuid4())})

        response = self.client.get(reverse("dashboard"))

        assert response.wsgi_request.tenant == home

    def test_exempt_paths_skip_resolution(self):
        _login(self.client)

        response = self.client.get("/accounts/logout/")

        assert response.wsgi_request.tenant is None
        assert response.wsgi_request.tenant_is_support_view is False


@pytest.mark.django_db
class TestTenantMiddlewareSupportView(TestCase):
    def test_superuser_in_support_view_gets_foreign_tenant(self):
        _login(self.client, superuser=True)
        foreign = baker.make("app.Tenant", name="Room One", slug="room-one")
        _enter_support(self.client, foreign)

        response = self.client.get(reverse("dashboard"))

        assert response.status_code == 200
        assert response.wsgi_request.tenant == foreign
        assert response.wsgi_request.tenant_is_support_view is True
        # The session is left alone: no silent fallback overwrote it.
        assert self.client.session[ACTIVE_TENANT_KEY] == str(foreign.id)

    def test_superuser_without_timestamp_falls_back(self):
        """A bare foreign id in a superuser's session is not enough: the
        support view has to have been entered through switch_tenant."""
        _, home = _login(self.client, superuser=True)
        foreign = baker.make("app.Tenant", name="Room One", slug="room-one")
        _set_session(self.client, {ACTIVE_TENANT_KEY: str(foreign.id)})

        response = self.client.get(reverse("dashboard"))

        assert response.wsgi_request.tenant == home
        assert response.wsgi_request.tenant_is_support_view is False

    def test_support_view_does_not_time_out(self):
        """There is no expiry: an old entry timestamp is still a valid
        marker. The view ends only via switch-back, the banner or a login."""
        _login(self.client, superuser=True)
        foreign = baker.make("app.Tenant", name="Room One", slug="room-one")
        _enter_support(
            self.client, foreign, started=timezone.now() - timedelta(days=3)
        )

        response = self.client.get(reverse("dashboard"))

        assert response.wsgi_request.tenant == foreign
        assert response.wsgi_request.tenant_is_support_view is True

    def test_deleted_foreign_workspace_falls_back(self):
        _, home = _login(self.client, superuser=True)
        _set_session(
            self.client,
            {
                ACTIVE_TENANT_KEY: str(uuid.uuid4()),
                SUPPORT_VIEW_STARTED_KEY: timezone.now().isoformat(),
            },
        )

        response = self.client.get(reverse("dashboard"))

        assert response.wsgi_request.tenant == home
        assert SUPPORT_VIEW_STARTED_KEY not in self.client.session

    def test_membership_in_active_tenant_is_never_a_support_view(self):
        user, home = _login(self.client, superuser=True)
        other = baker.make("app.Tenant", name="Other", slug="other")
        baker.make("app.Membership", user=user, tenant=other, role="member")
        _enter_support(self.client, other)  # stale timestamp, real membership

        response = self.client.get(reverse("dashboard"))

        assert response.wsgi_request.tenant == other
        assert response.wsgi_request.tenant_is_support_view is False
        assert SUPPORT_VIEW_STARTED_KEY not in self.client.session

    def test_writes_in_support_view_are_logged(self):
        user, _ = _login(self.client, superuser=True)
        foreign = baker.make("app.Tenant", name="Room One", slug="room-one")
        _enter_support(self.client, foreign)

        with self.assertLogs("app.support_view", level=logging.WARNING) as logs:
            self.client.post(reverse("create_stack"), {"name": "Support stack"})

        joined = "\n".join(logs.output)
        assert "support view write" in joined
        assert "room-one" in joined
        assert reverse("create_stack") in joined
        assert user.email in joined
        assert str(user.pk) in joined

    def test_support_view_logger_writes_timestamped_lines(self):
        """The audit trail must say when. Django leaves non-django loggers to
        Python's last-resort handler (bare message, no time), so settings
        route this logger through a timestamped formatter."""
        import logging as _logging
        import re

        logger = _logging.getLogger("app.support_view")
        handlers = [h for h in logger.handlers if h.formatter]
        assert handlers, "app.support_view has no configured handler"
        record = logger.makeRecord(
            "app.support_view", _logging.WARNING, __file__, 0, "probe", (), None
        )
        line = handlers[0].formatter.format(record)
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", line), line
        assert line.endswith("WARNING app.support_view: probe")

    def test_reads_in_support_view_are_not_logged_as_writes(self):
        _login(self.client, superuser=True)
        foreign = baker.make("app.Tenant", name="Room One", slug="room-one")
        _enter_support(self.client, foreign)

        with self.assertNoLogs("app.support_view", level=logging.WARNING):
            self.client.get(reverse("dashboard"))

    def test_login_resets_support_view(self):
        """Django keeps session data across a same-user login, so the
        user_logged_in signal must drop the support view."""
        from django.contrib.auth import login
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.test import RequestFactory

        user = baker.make("app.User", is_superuser=True)
        foreign = baker.make("app.Tenant", name="Room One", slug="room-one")
        request = RequestFactory().get("/")
        SessionMiddleware(lambda r: None).process_request(request)
        request.session[ACTIVE_TENANT_KEY] = str(foreign.id)
        request.session[SUPPORT_VIEW_STARTED_KEY] = timezone.now().isoformat()
        request.session.save()

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")

        assert SUPPORT_VIEW_STARTED_KEY not in request.session
        assert ACTIVE_TENANT_KEY not in request.session
