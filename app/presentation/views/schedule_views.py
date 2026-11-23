from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from app.presentation.schedule_preview import SchedulePreview


@login_required
@require_GET
def schedule_preview(request):
    """The schedule editor's live reading of a cron expression
    (``SchedulePreview``): words and next times, or the error."""
    preview = SchedulePreview(request.GET.get("cron", ""), request.GET.get("tz") or "UTC")
    return JsonResponse(preview.as_dict(timezone.now()))
