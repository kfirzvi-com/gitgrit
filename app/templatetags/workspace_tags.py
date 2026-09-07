from zlib import crc32

from django import template

register = template.Library()

# One badge colour per workspace, picked from the slug so it is stable across
# sessions and devices. Lets a user tell two same-named workspaces apart at a
# glance in the navbar.
BADGE_CLASSES = (
    "bg-primary text-primary-content",
    "bg-secondary text-secondary-content",
    "bg-accent text-accent-content",
    "bg-info text-info-content",
    "bg-success text-success-content",
    "bg-warning text-warning-content",
    "bg-error text-error-content",
    "bg-neutral text-neutral-content",
)


@register.filter
def workspace_badge_class(tenant):
    key = (getattr(tenant, "slug", None) or str(tenant)).encode()
    return BADGE_CLASSES[crc32(key) % len(BADGE_CLASSES)]
