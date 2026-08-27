from django.test import SimpleTestCase

from app.application import event_bus


class EventBusTests(SimpleTestCase):
    def test_publish_invokes_subscribers(self):
        seen = []

        class _Evt:
            pass

        handler = lambda e: seen.append(e)  # noqa: E731
        event_bus.subscribe(_Evt, handler)
        evt = _Evt()
        event_bus.publish(evt)
        self.assertEqual(seen, [evt])

    def test_subscribe_is_idempotent(self):
        calls = []

        class _Evt:
            pass

        handler = lambda e: calls.append(1)  # noqa: E731
        event_bus.subscribe(_Evt, handler)
        event_bus.subscribe(_Evt, handler)  # same handler twice
        event_bus.publish(_Evt())
        self.assertEqual(calls, [1])

    def test_handler_exception_is_swallowed(self):
        class _Evt:
            pass

        def boom(_):
            raise ValueError("nope")

        event_bus.subscribe(_Evt, boom)
        # Must not raise — a misbehaving reaction can't break the domain op.
        event_bus.publish(_Evt())

    def test_publish_returns_non_none_handler_results(self):
        class _Evt:
            pass

        event_bus.subscribe(_Evt, lambda e: {"ran": 1})
        event_bus.subscribe(_Evt, lambda e: None)
        self.assertEqual(event_bus.publish(_Evt()), [{"ran": 1}])

    def test_failing_handler_contributes_no_result(self):
        class _Evt:
            pass

        def boom(_):
            raise ValueError("nope")

        event_bus.subscribe(_Evt, boom)
        event_bus.subscribe(_Evt, lambda e: "ok")
        self.assertEqual(event_bus.publish(_Evt()), ["ok"])
