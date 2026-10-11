"""The notifications side pane: opened from the navbar bell over the current
page, never a page of its own. Every view here serves the pane's fragment or
acts on one inbox item; ``open_notification`` is the only one that navigates.
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from app.domain.models import NotificationDelivery

HISTORY_LIMIT = 50
HISTORY_PAGE = 5

# Sent with every response that changes read state, so the navbar bell
# re-fetches its count without waiting for its 30-second poll.
COUNT_CHANGED_EVENT = "notificationsCountChanged"


def _group_by_day(deliveries):
    """Split deliveries into ("Today", [...]), ("Yesterday", [...]), ("Older", [...])
    by the notification's creation day in the current timezone. Order within a
    group is kept; empty groups are left out."""
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    groups = {"Today": [], "Yesterday": [], "Older": []}
    for delivery in deliveries:
        day = timezone.localtime(delivery.notification.created_at).date()
        if day >= today:
            groups["Today"].append(delivery)
        elif day == yesterday:
            groups["Yesterday"].append(delivery)
        else:
            groups["Older"].append(delivery)
    return [(label, items) for label, items in groups.items() if items]


def _inbox(request):
    """This user's inbox deliveries in the active workspace."""
    if not request.tenant:
        return NotificationDelivery.objects.none()
    return NotificationDelivery.objects.filter(
        recipient=request.user,
        channel="inbox",
        notification__tenant=request.tenant,
    )


def _panel(request):
    """Render the pane's contents: Active (unread, newest first) grouped by day,
    and History (read, newest first)."""
    sent = _inbox(request).filter(status=NotificationDelivery.Status.SENT).select_related("notification")
    active = list(sent.filter(read_at__isnull=True).order_by("-notification__created_at"))
    history = sent.filter(read_at__isnull=False).order_by("-notification__created_at")[:HISTORY_LIMIT]
    return render(
        request,
        "partials/notifications_panel.html",
        {
            "active": active,
            "active_groups": _group_by_day(active),
            "history": history,
            "history_page": HISTORY_PAGE,
        },
    )


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
    """Mark the item read, then send the user to what it is about."""
    delivery = get_object_or_404(_inbox(request).select_related("notification"), pk=pk)
    if delivery.read_at is None:
        delivery.read_at = timezone.now()
        delivery.save(update_fields=["read_at"])
    url = delivery.notification.url
    # Notices link into GitGrit; anything else stored there is not followed.
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(url)
    return redirect("dashboard")


@login_required
@require_POST
def mark_all_read(request):
    _inbox(request).filter(read_at__isnull=True).update(
        read_at=timezone.now()
    )
    response = _panel(request)
    response["HX-Trigger"] = COUNT_CHANGED_EVENT
    return response


@login_required
@require_POST
def mark_read(request, pk):
    """Mark one item read without leaving the page."""
    delivery = get_object_or_404(_inbox(request), pk=pk)
    if delivery.read_at is None:
        delivery.read_at = timezone.now()
        delivery.save(update_fields=["read_at"])
    response = _panel(request)
    response["HX-Trigger"] = COUNT_CHANGED_EVENT
    return response
