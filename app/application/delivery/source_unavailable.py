class SourceUnavailable(Exception):
    """A deployment source could not be read: the token lacks a permission,
    the strategy is missing a setting, or the platform has no such signal.
    The message says which, in words a workspace admin can act on."""
