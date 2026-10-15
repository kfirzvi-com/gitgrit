"""Small helpers for views that answer HTMX requests in place."""
import json


def toast(response, text: str, level: str = "success"):
    """Show ``text`` as a toast once HTMX has swapped ``response`` in
    (components/toasts.html). ``level``: success, error, warning or info."""
    triggers = _triggers(response.get("HX-Trigger", ""))
    triggers["toast"] = {"level": level, "text": text}
    response["HX-Trigger"] = json.dumps(triggers)
    return response


def _triggers(header: str) -> dict:
    """An existing HX-Trigger header as a dict: JSON, or comma-separated
    event names."""
    header = header.strip()
    if not header:
        return {}
    if header.startswith("{"):
        return json.loads(header)
    return {name.strip(): None for name in header.split(",") if name.strip()}
