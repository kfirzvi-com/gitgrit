import base64
from pathlib import Path

from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from app.application.grading_service import grade_for_project
from app.domain import grading
from app.domain.models import Project

_LOGO_PATH = Path(__file__).resolve().parent.parent.parent / "static" / "app" / "images" / "logo.svg"

try:
    _LOGO_DATA_URI = "data:image/svg+xml;base64," + base64.b64encode(_LOGO_PATH.read_bytes()).decode()
except Exception:
    _LOGO_DATA_URI = None

# Badge colour per tone (see ``grading.tone_for``). The badge is an external
# SVG, so it needs hex: these copy the --gg-grade-* tokens in
# app/static/app/design-tokens.css (sRGB of the oklch values).
_COLOR = {
    grading.TONE_GOOD: "#00c584",       # --gg-success oklch(72% 0.177 163)
    grading.TONE_ATTENTION: "#efa800",  # --gg-warning oklch(78% 0.170 80)
    grading.TONE_FAILING: "#f14e46",    # --gg-error oklch(65% 0.200 27)
    grading.TONE_UNKNOWN: "#51555e",    # --gg-text-dimmer oklch(45% 0.015 264)
}


def project_badge(request, pk):
    """Serve an SVG grade badge for a project. Unauthenticated."""
    project = get_object_or_404(Project, pk=pk)

    # The same grade the project page shows: the letter from the latest
    # counting default-branch result per attached standard.
    svg = _render_badge(grade_for_project(project).grade.letter)

    response = HttpResponse(svg, content_type="image/svg+xml")
    response["Cache-Control"] = "public, max-age=300"  # 5 min cache
    return response


def _render_badge(letter):
    """Render a shields.io-style SVG badge with the GitGrit logo as label:
    the letter, coloured by its tone, or "no grade"."""
    value = letter if letter != grading.NO_GRADE else "no grade"
    color = _COLOR[grading.tone_for(letter)]

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

    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{total_width}" height="20" role="img" aria-label="GitGrit grade: {value}">
  <title>GitGrit grade: {value}</title>
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
