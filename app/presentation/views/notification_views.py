"""The notifications side pane: opened from the navbar bell over the current
page, never a page of its own. Every view here serves the pane's fragment or
acts on one inbox item; ``open_notification`` is the only one that navigates.

The pane has two kinds of content. "Needs attention" is the workspace's
current state (the same list as the dashboard) and is always shown; Active
and History are the user's ``Inbox``, which owns the reading rules.
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from app.application.standard_results import attention_items
from app.domain.models import InboxItem
from app.domain.notifications.inbox import Inbox

HISTORY_PAGE = 5

# Sent with every response that changes read state, so the navbar bell
# re-fetches its count without waiting for its 30-second poll.
COUNT_CHANGED_EVENT = "notificationsCountChanged"


def _inbox(request) -> Inbox:
    tenant = request.tenant
    return Inbox(request.user.pk, tenant.pk if tenant else None)


def _group_by_day(items):
    """Split items into ("Today", [...]), ("Yesterday", [...]), ("Older", [...])
    by the notification's creation day in the current timezone. Order within a
    group is kept; empty groups are left out."""
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    groups = {"Today": [], "Yesterday": [], "Older": []}
    for item in items:
        day = timezone.localtime(item.notification.created_at).date()
        if day >= today:
            groups["Today"].append(item)
        elif day == yesterday:
            groups["Yesterday"].append(item)
        else:
            groups["Older"].append(item)
    return [(label, group) for label, group in groups.items() if group]


def _panel(request):
    """Render the pane's contents: Needs attention, Active grouped by day, and
    History."""
    inbox = _inbox(request)
    active = inbox.active()
    attention = attention_items(request.tenant) if request.tenant else []
    return render(
        request,
        "partials/notifications_panel.html",
        {
            "attention_items": attention,
            "attention_total": len(attention),
            "active": active,
            "active_groups": _group_by_day(active),
            "history": inbox.history(),
            "history_page": HISTORY_PAGE,
        },
    )


def _panel_after_change(request):
    response = _panel(request)
    response["HX-Trigger"] = COUNT_CHANGED_EVENT
    return response


def _mark_read(request, pk) -> InboxItem:
    try:
        return _inbox(request).mark_read(pk)
    except InboxItem.DoesNotExist:
        raise Http404("No such notification") from None


def _mark_unread(request, pk) -> InboxItem:
    try:
        return _inbox(request).mark_unread(pk)
    except InboxItem.DoesNotExist:
        raise Http404("No such notification") from None


@login_required
@require_GET
def notification_panel(request):
    """The pane's contents, fetched when the bell opens it and every 30 seconds
    while it stays open."""
    return _panel(request)


@login_required
@require_GET
def notification_bell(request):
    """The navbar bell on its own, for the HTMX poll that keeps its count fresh.
    The unread count comes from the ``notification_context`` context processor."""
    return render(request, "components/notification_bell.html")


@login_required
@require_GET
def open_notification(request, pk):
    """Read the item, then send the user to what it is about."""
    url = _mark_read(request, pk).notification.url
    # Notifications link into GitGrit; anything else stored there is not followed.
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(url)
    return redirect("dashboard")


@login_required
@require_POST
def mark_read(request, pk):
    """Read one item without leaving the page."""
    _mark_read(request, pk)
    return _panel_after_change(request)


@login_required
@require_POST
def mark_unread(request, pk):
    """Put one read item back in Active."""
    _mark_unread(request, pk)
    return _panel_after_change(request)


@login_required
@require_POST
def mark_all_read(request):
    _inbox(request).mark_all_read()
    return _panel_after_change(request)
