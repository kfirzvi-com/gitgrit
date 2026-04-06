"""Resolve external platform identities to GitGrit users.

When a webhook event arrives with an actor (e.g. a GitHub username), this
module maps it to a GitGrit User by looking up connected social accounts.
"""

from __future__ import annotations

from allauth.socialaccount.models import SocialAccount

from app.domain.models import User


def resolve_user(platform: str, actor: str | None) -> User | None:
    """Map a platform actor to a GitGrit user.

    Looks up the SocialAccount where the provider matches the platform
    and the extra_data contains the actor's username.

    Args:
        platform: "github" or "gitlab"
        actor: The username on the platform (e.g. "octocat")

    Returns:
        The matching User, or None if no connection found.
    """
    if not actor:
        return None

    # Map platform names to allauth provider IDs and extra_data keys
    lookup = _PLATFORM_LOOKUP.get(platform)
    if not lookup:
        return None

    provider_id, username_key = lookup

    # Query SocialAccount by provider, then filter by username in extra_data
    # Using extra_data JSON lookup (PostgreSQL supports this natively)
    account = (
        SocialAccount.objects.filter(
            provider=provider_id,
            **{f"extra_data__{username_key}": actor},
        )
        .select_related("user")
        .first()
    )
    return account.user if account else None


# Maps platform name -> (allauth provider ID, extra_data key for username)
_PLATFORM_LOOKUP = {
    "github": ("github", "login"),
    "gitlab": ("gitlab", "username"),
}
