from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import TemplateView

from app.domain.models import NotificationDelivery

HISTORY_LIMIT = 50


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
        context["active"] = sent.filter(read_at__isnull=True).order_by("-notification__created_at")
        context["history"] = sent.filter(read_at__isnull=False).order_by("-read_at")[:HISTORY_LIMIT]
        return context


@login_required
@require_GET
def open_notification(request, pk):
    """Mark the item read, then send the user to what it is about."""
    delivery = get_object_or_404(_inbox(request).select_related("notification"), pk=pk)
    if delivery.read_at is None:
        delivery.read_at = timezone.now()
        delivery.save(update_fields=["read_at"])
    return redirect(delivery.notification.url or "notification_list")


@login_required
@require_POST
def mark_all_read(request):
    _inbox(request).filter(read_at__isnull=True).update(read_at=timezone.now())
    return redirect("notification_list")
