"""The Projects, Standards and Marketplace pages' bulk bars: one POST per change, for the
selected items (``ids``). The answer is a toast and a ``smart-table:reload``
trigger, on which the page fetches its table again in place (sort, groups
and filter kept: they ride in the address)."""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.views.decorators.http import require_POST

from app.application.bulk_edit import MarketplaceBulkInstall, ProjectBulkEdit, StandardBulkEdit
from app.application.errors import NotFoundError
from app.domain.importance import UnknownImportance
from app.presentation.htmx import toast


def _answer(text: str, level: str, reload: bool) -> HttpResponse:
    response = HttpResponse("")
    if reload:
        response["HX-Trigger"] = '{"smart-table:reload": true}'
    return toast(response, text, level)


def _bulk(request, edit, **extra):
    if not request.tenant:
        return _answer("No active workspace.", "error", reload=False)
    ids = request.POST.getlist("ids")
    if not ids:
        return _answer("Select something first.", "warning", reload=False)
    try:
        result = edit(request.tenant, request.user).apply(
            request.POST.get("action", ""), ids, request.POST.get("value", ""), **extra
        )
    except (NotFoundError, UnknownImportance, ValueError) as error:
        return _answer(str(error), "error", reload=False)
    return _answer(result.summary, result.level, reload=True)


@login_required
@require_POST
def bulk_edit_standards(request):
    return _bulk(request, StandardBulkEdit)


@login_required
@require_POST
def bulk_install_marketplace(request):
    return _bulk(request, MarketplaceBulkInstall)


@login_required
@require_POST
def bulk_edit_projects(request):
    return _bulk(request, ProjectBulkEdit, importance_value=request.POST.get("importance", ""))
