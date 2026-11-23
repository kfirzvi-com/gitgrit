from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from app.presentation.schedule_preview import SchedulePreview


@login_required
@require_GET
def schedule_preview(request):
    """The schedule editor's live reading of a cron expression in its time
    zone (``SchedulePreview``): words and next times (also in the viewer's
    ``viewer_tz``), or the error."""
    preview = SchedulePreview(
        request.GET.get("cron", ""), request.GET.get("tz") or "UTC", request.GET.get("viewer_tz", "")
    )
    return JsonResponse(preview.as_dict(timezone.now()))
