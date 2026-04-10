import base64
from pathlib import Path

from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from app.domain.models import PolicyExecution, Project

_LOGO_PATH = Path(__file__).resolve().parent.parent.parent / "static" / "app" / "images" / "logo.svg"

try:
    _LOGO_DATA_URI = "data:image/svg+xml;base64," + base64.b64encode(_LOGO_PATH.read_bytes()).decode()
except Exception:
    _LOGO_DATA_URI = None


def project_badge(request, pk):
    """Serve an SVG compliance badge for a project. Unauthenticated."""
    project = get_object_or_404(Project, pk=pk)

    # Calculate compliance score from latest executions
    executions = (
        PolicyExecution.objects.filter(project=project)
        .select_related("policy")
        .order_by("-created_at")[:200]
    )
    seen = {}
    for ex in executions:
        key = ex.policy_id or ex.policy_name
        if key not in seen:
            seen[key] = ex

    latest = list(seen.values())
    if latest:
        score = round(sum(ex.score for ex in latest) / len(latest))
        all_passed = all(ex.status == "passed" for ex in latest)
    else:
        score = None
        all_passed = False

    svg = _render_badge(score, all_passed)

    response = HttpResponse(svg, content_type="image/svg+xml")
    response["Cache-Control"] = "public, max-age=300"  # 5 min cache
    return response


def _render_badge(score, all_passed):
    """Render a shields.io-style SVG badge with the GitGrit logo as label."""
    if score is None:
        value = "no data"
        color = "#9e9e9e"
    elif all_passed:
        value = f"{score}%"
        color = "#4caf50"
    elif score >= 80:
        value = f"{score}%"
        color = "#4caf50"
    elif score >= 50:
        value = f"{score}%"
        color = "#ff9800"
    else:
        value = f"{score}%"
        color = "#f44336"

    logo_size = 14
    label_width = logo_size + 12  # 6px padding each side
    value_width = len(value) * 7 + 12
    total_width = label_width + value_width

    logo_x = (label_width - logo_size) // 2
    logo_y = (20 - logo_size) // 2

    logo_element = (
        f'<image x="{logo_x}" y="{logo_y}" width="{logo_size}" height="{logo_size}" href="{_LOGO_DATA_URI}"/>'
        if _LOGO_DATA_URI
        else f'<text x="{label_width / 2}" y="13" fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,sans-serif" font-size="11">g</text>'
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{total_width}" height="20" role="img" aria-label="GitGrit compliance: {value}">
  <title>GitGrit compliance: {value}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#s)"/>
  </g>
  {logo_element}
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" text-rendering="geometricPrecision" font-size="11">
    <text x="{label_width + value_width / 2}" y="14" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="{label_width + value_width / 2}" y="13">{value}</text>
  </g>
</svg>'''
