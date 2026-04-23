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
            try:
                from app.infrastructure.mcp.server import mcp_app  # noqa: F401
            except Exception:
                return HttpResponse("MCP_UNAVAILABLE", status=503)
            return HttpResponse("OK")
        return self.get_response(request)
