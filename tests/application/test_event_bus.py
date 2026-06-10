from app.application import event_bus


def test_publish_invokes_subscribers():
    seen = []

    class _Evt:
        pass

    handler = lambda e: seen.append(e)  # noqa: E731
    event_bus.subscribe(_Evt, handler)
    evt = _Evt()
    event_bus.publish(evt)
    assert seen == [evt]


def test_subscribe_is_idempotent():
    calls = []

    class _Evt:
        pass

    handler = lambda e: calls.append(1)  # noqa: E731
    event_bus.subscribe(_Evt, handler)
    event_bus.subscribe(_Evt, handler)  # same handler twice
    event_bus.publish(_Evt())
    assert calls == [1]


def test_handler_exception_is_swallowed():
    class _Evt:
        pass

    def boom(_):
        raise ValueError("nope")

    event_bus.subscribe(_Evt, boom)
    # Must not raise — a misbehaving reaction can't break the domain op.
    event_bus.publish(_Evt())
