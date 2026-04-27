from django.http import HttpResponse, JsonResponse

from app.application.api_token_service import resolve_api_token
from app.infrastructure.mcp.setup.rule_files import render

_SUPPORTED_CLIENTS = ("cursor", "cline")


def _bearer_token(request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header[7:]


def export_setup_file(request, client: str):
    """GET /api/setup/<client> — return rule-file content for a generic MCP client.

    Same kind-gate as the ``export_setup_files`` MCP tool: only generic-kind
    tokens may pull rule files. Bearer auth uses the shared resolver in
    ``app.application.api_token_service`` so the wire path is identical to MCP.
    """
    if request.method != "GET":
        return JsonResponse({"error": "method_not_allowed"}, status=405)

    raw_token = _bearer_token(request)
    if raw_token is None:
        return JsonResponse({"error": "missing_bearer_token"}, status=401)
    try:
        api_token = resolve_api_token(raw_token)
    except PermissionError:
        return JsonResponse({"error": "invalid_token"}, status=401)

    if api_token.client_kind != "generic":
        return JsonResponse(
            {
                "error": "not_applicable",
                "message": (
                    "This endpoint serves rule files for non-Claude MCP clients. "
                    "Generate a generic-kind API token in the GitGrit profile page."
                ),
            },
            status=403,
        )

    if client not in _SUPPORTED_CLIENTS:
        return JsonResponse(
            {"error": "unsupported_client", "supported": list(_SUPPORTED_CLIENTS)},
            status=404,
        )

    _path, content = render(client)  # type: ignore[arg-type]
    return HttpResponse(content, content_type="text/plain; charset=utf-8")
