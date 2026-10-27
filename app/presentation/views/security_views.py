"""How to report a vulnerability (SOC 2 CC2.3).

``/.well-known/security.txt`` is the RFC 9116 file security researchers and
scanners look for; ``/security/`` is the stable address the footer links to.
Both are public and list the same contacts as SECURITY.md.
"""
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_safe


@require_safe
def security_txt(request):
    site = settings.SITE_URL.rstrip("/")
    lines = [f"Contact: mailto:{settings.SECURITY_CONTACT_EMAIL}"]
    # The default advisory page lives on GitHub, which an air-gapped install
    # can't reach; list it only if the operator pointed it somewhere.
    if not settings.AIRGAPPED or settings.SECURITY_ADVISORY_URL_IS_CUSTOM:
        lines.append(f"Contact: {settings.SECURITY_ADVISORY_URL}")
    lines += [
        f"Expires: {settings.SECURITY_TXT_EXPIRES}",
        f"Policy: {site}/security/",
    ]
    # RFC 9116: Canonical must be an https URL.
    if site.startswith("https://"):
        lines.append(f"Canonical: {site}/.well-known/security.txt")
    lines.append("Preferred-Languages: en")
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain; charset=utf-8")


@require_safe
def security_policy(request):
    return redirect(settings.SECURITY_POLICY_URL)
