"""How a page's bulk bar is answered (smart_table_selection.js): one POST
per change, for the selected items (``ids``), run by that context's bulk
edit (``ProjectBulkEdit``, ``StandardBulkEdit``, ``MarketplaceBulkInstall``).
The answer is a toast and a ``smart-table:reload`` trigger, on which the page
fetches its table again in place (sort, groups and filter kept: they ride in
the address)."""
from django.http import HttpResponse

from app.application.errors import NotFoundError
from app.domain.importance import UnknownImportance
from app.presentation.htmx import toast


class BulkEditAnswer:
    """Runs one bulk change from a request and answers it."""

    @classmethod
    def to(cls, request, edit, **extra) -> HttpResponse:
        """``edit`` is the context's bulk edit class; ``extra`` goes to its
        ``apply`` beside the action, ids and value."""
        if not request.tenant:
            return cls._answer("No active workspace.", "error", reload=False)
        ids = request.POST.getlist("ids")
        if not ids:
            return cls._answer("Select something first.", "warning", reload=False)
        try:
            result = edit(request.tenant, request.user).apply(
                request.POST.get("action", ""), ids, request.POST.get("value", ""), **extra
            )
        except (NotFoundError, UnknownImportance, ValueError) as error:
            return cls._answer(str(error), "error", reload=False)
        return cls._answer(result.summary, result.level, reload=True)

    @staticmethod
    def _answer(text: str, level: str, reload: bool) -> HttpResponse:
        response = HttpResponse("")
        if reload:
            response["HX-Trigger"] = '{"smart-table:reload": true}'
        return toast(response, text, level)
