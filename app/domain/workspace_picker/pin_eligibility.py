class PinEligibility:
    """Who may pin a workspace: anyone who can open it — a member, or a
    superuser (who can open every workspace as support)."""

    @staticmethod
    def allows(*, is_member: bool, is_superuser: bool) -> bool:
        return is_member or is_superuser
