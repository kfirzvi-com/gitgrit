"""What the user time zone feature announces (TimeZoneAsked, TimeZoneChosen),
for whoever listens: only after the change is saved, and only when it
happened."""
from django.test import TestCase
from model_bakery import baker

from app.application import event_bus, subscribers
from app.application.user_time_zone_setting import ask_for_time_zone, change_time_zone
from app.domain.events import TimeZoneAsked, TimeZoneChosen


class AnnouncedEventsTests(TestCase):
    def setUp(self):
        event_bus.clear()
        self.addCleanup(subscribers.register)
        self.addCleanup(event_bus.clear)
        self.heard = []
        event_bus.subscribe(TimeZoneAsked, self.heard.append)
        event_bus.subscribe(TimeZoneChosen, self.heard.append)
        self.user = baker.make("app.User")

    def test_asking_announces_once_after_the_save(self):
        with self.captureOnCommitCallbacks() as pending:
            ask_for_time_zone(self.user, "Asia/Jerusalem")
            self.assertEqual(self.heard, [])  # not before the save commits
        for callback in pending:
            callback()
        with self.captureOnCommitCallbacks(execute=True):
            ask_for_time_zone(self.user, "Asia/Jerusalem")
        self.assertEqual(self.heard, [TimeZoneAsked(user_id=str(self.user.pk))])

    def test_a_device_on_utc_announces_nothing(self):
        with self.captureOnCommitCallbacks(execute=True):
            ask_for_time_zone(self.user, "UTC")
        self.assertEqual(self.heard, [])

    def test_choosing_announces_it(self):
        with self.captureOnCommitCallbacks(execute=True):
            change_time_zone(self.user, "Asia/Jerusalem")
        self.assertEqual(self.heard, [TimeZoneChosen(user_id=str(self.user.pk))])
