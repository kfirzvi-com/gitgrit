from django.conf import settings
from django.http import HttpResponse


class HealthCheckMiddleware:
    """Respond to /up/ before ALLOWED_HOSTS validation.

    kamal-proxy sends healthchecks with the container name as the Host header,
    which Django rejects. This middleware intercepts the healthcheck path before
    SecurityMiddleware runs.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/up/":
            return HttpResponse("OK")
        return self.get_response(request)


class PermissionsPolicyMiddleware:
    """Send ``Permissions-Policy`` from ``settings.PERMISSIONS_POLICY``.

    Each feature maps to its allowlist: ``[]`` denies it everywhere,
    ``"self"`` / ``"*"`` are passed through as tokens, and any other entry is
    an origin and is quoted, as the header syntax requires.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def build(policy):
        def token(origin):
            return origin if origin in ("self", "*") else f'"{origin}"'

        return ", ".join(
            f"{feature}=({' '.join(token(o) for o in origins)})"
            for feature, origins in policy.items()
        )

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", self.build(settings.PERMISSIONS_POLICY))
        return response
