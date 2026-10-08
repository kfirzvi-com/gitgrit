from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import TemplateView

from app.domain.models import NotificationDelivery

HISTORY_LIMIT = 50
HISTORY_PAGE = 5


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


class NotificationListView(LoginRequiredMixin, TemplateView):
    template_name = "pages/notifications.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sent = _inbox(self.request).filter(status=NotificationDelivery.Status.SENT).select_related("notification")
        active = list(
            sent.filter(read_at__isnull=True).order_by(
                F("pinned_at").desc(nulls_last=True), "-notification__created_at"
            )
        )
        context["active"] = active
        context["active_groups"] = _group_by_day(active)
        context["history"] = sent.filter(read_at__isnull=False).order_by("-read_at")[:HISTORY_LIMIT]
        context["history_page"] = HISTORY_PAGE
        return context


@login_required
@require_GET
def open_notification(request, pk):
    """Mark the item read (unless pinned), then send the user to what it is about."""
    delivery = get_object_or_404(_inbox(request).select_related("notification"), pk=pk)
    if delivery.read_at is None and not delivery.is_pinned:
        delivery.read_at = timezone.now()
        delivery.save(update_fields=["read_at"])
    url = delivery.notification.url
    # Notices link into GitGrit; anything else stored there is not followed.
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(url)
    return redirect("notification_list")


@login_required
@require_POST
def mark_all_read(request):
    _inbox(request).filter(read_at__isnull=True, pinned_at__isnull=True).update(
        read_at=timezone.now()
    )
    return redirect("notification_list")


@login_required
@require_POST
def toggle_pin(request, pk):
    """Pin keeps the item in Active, unread, until the user unpins it.
    Pinning a read item brings it back to Active."""
    delivery = get_object_or_404(_inbox(request), pk=pk)
    if delivery.is_pinned:
        delivery.pinned_at = None
    else:
        delivery.pinned_at = timezone.now()
        delivery.read_at = None
    delivery.save(update_fields=["pinned_at", "read_at"])
    return redirect("notification_list")
