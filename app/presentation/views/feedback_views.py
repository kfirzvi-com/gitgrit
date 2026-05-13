import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_POST

from app.domain.models import FeedbackReport


MAX_BODY_LEN = 4000
MAX_CONTEXT_LEN = 8000


@login_required
@require_POST
def submit_feedback(request):
    body = (request.POST.get("body") or "").strip()
    if not body:
        return render(
            request,
            "partials/feedback_error.html",
            {"msg": "Please add a message."},
            status=400,
        )
    if len(body) > MAX_BODY_LEN:
        return render(
            request,
            "partials/feedback_error.html",
            {"msg": f"Too long (max {MAX_BODY_LEN} chars)."},
            status=400,
        )

    raw_context = (request.POST.get("context") or "").strip()
    if len(raw_context) > MAX_CONTEXT_LEN:
        return render(
            request,
            "partials/feedback_error.html",
            {"msg": f"Context block too large (max {MAX_CONTEXT_LEN} chars). Trim it and resend."},
            status=400,
        )
    if raw_context:
        try:
            context = json.loads(raw_context)
        except json.JSONDecodeError:
            return render(
                request,
                "partials/feedback_error.html",
                {"msg": "Context block is not valid JSON. Fix it or clear it and resend."},
                status=400,
            )
        if not isinstance(context, dict):
            return render(
                request,
                "partials/feedback_error.html",
                {"msg": "Context must be a JSON object."},
                status=400,
            )
    else:
        context = {}

    tenant = getattr(request, "tenant", None)
    FeedbackReport.objects.create(
        user=request.user,
        user_email=request.user.email or "",
        tenant_slug=tenant.slug if tenant else "",
        body=body,
        context=context,
    )
    return render(request, "partials/feedback_thanks.html")
