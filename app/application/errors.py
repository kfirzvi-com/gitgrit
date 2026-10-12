class NotFoundError(ValueError):
    """A tenant-scoped lookup missed.

    Subclasses ``ValueError`` so existing callers (web views) that
    catch ``ValueError`` keep working, while the REST API can tell a miss
    (404) apart from invalid input such as bad standard code (400).
    """
