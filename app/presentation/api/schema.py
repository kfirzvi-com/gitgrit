def public_api_only(endpoints, **kwargs):
    """drf-spectacular preprocessing hook: document ``/api/v1/`` only.

    Webhook receivers are DRF views too, but they are not part of the public
    contract.
    """
    return [e for e in endpoints if e[0].startswith("/api/v1/")]
