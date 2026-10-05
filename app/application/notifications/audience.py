"""Turn an Audience into the user ids that should be notified."""

from app.domain.models import Membership
from app.domain.notifications import Audience


def resolve(
    audience: Audience,
    tenant_id: str,
    mentioned_user_ids: tuple[str, ...] = (),
) -> list[str]:
    """Return distinct member user ids, in a stable order.

    Everyone is filtered through Membership of the tenant, including ids named
    directly, so we never notify across workspaces. A superuser without a
    Membership row resolves to nothing; that is expected.
    """
    named = {str(u) for u in (*audience.user_ids, *mentioned_user_ids)}
    by_role = {
        str(u)
        for u in Membership.objects.filter(
            tenant_id=tenant_id, role__in=audience.roles
        ).values_list("user_id", flat=True)
    }
    if named:
        named &= {
            str(u)
            for u in Membership.objects.filter(
                tenant_id=tenant_id, user_id__in=named
            ).values_list("user_id", flat=True)
        }
    return sorted(by_role | named)
