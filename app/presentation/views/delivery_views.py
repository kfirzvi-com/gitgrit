"""The project page's Delivery tab: how often the project ships (DORA
deployment frequency), how deployments are counted, and the latest ones."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from app.application.delivery import DeliveryReport, DeliverySyncRequest, DeliverySyncSchedule
from app.models import DeliverySettings, Project
from app.presentation.delivery_settings_form import DeliverySettingsForm


def _project(request, pk) -> Project:
    return get_object_or_404(Project.objects.select_related("platform_connection"), pk=pk, tenant=request.tenant)


def _render(request, project: Project, form: DeliverySettingsForm | None = None, open_settings: bool = False):
    report = DeliveryReport.for_project(project)
    busiest = max((week.deployments for week in report.frequency.weeks), default=0)
    return render(
        request,
        "partials/project_delivery.html",
        {
            "project": project,
            "report": report,
            "settings": report.settings,
            "weeks": [
                (week, round(100 * week.deployments / busiest) if busiest else 0) for week in report.frequency.weeks
            ],
            "form": form or DeliverySettingsForm(instance=report.settings),
            "open_settings": open_settings,
            "next_refresh": _next_refresh(report.settings),
            "sync_minutes": int(DeliverySyncSchedule.policy().interval.total_seconds() // 60),
        },
    )


def _next_refresh(settings: DeliverySettings):
    """When Refresh works again, while the last sync is too recent."""
    if settings.refreshed_at is None or settings.refreshing:
        return None
    policy = DeliverySyncSchedule.policy()
    if policy.may_refresh(settings.refreshed_at, timezone.now()):
        return None
    return policy.next_refresh(settings.refreshed_at)


@login_required
def project_delivery(request, pk):
    """The tab's content. The first visit starts the first look for
    deployments; while one runs, the content polls itself."""
    project = _project(request, pk)
    settings, _ = DeliverySettings.objects.get_or_create(project=project)
    if settings.refreshed_at is None and settings.refresh_requested_at is None:
        DeliverySyncRequest.send(project)
    return _render(request, project)


@login_required
@require_POST
def project_delivery_refresh(request, pk):
    """Sync now, unless the last sync was moments ago (then the tab says
    when Refresh works again)."""
    project = _project(request, pk)
    DeliverySyncRequest.refresh(project)
    return _render(request, project)


@login_required
@require_POST
def project_delivery_settings(request, pk):
    """Save how deployments are counted, then count them again."""
    project = _project(request, pk)
    settings, _ = DeliverySettings.objects.get_or_create(project=project)
    form = DeliverySettingsForm(request.POST, instance=settings)
    if not form.is_valid():
        return _render(request, project, form=form, open_settings=True)
    form.save()
    if form.has_changed():
        DeliverySyncRequest.send(project)
    return _render(request, project)
