"""A standard can be turned on or off, except that a draft can't be turned on:
drafts never run. Turning one on is reported as runnable so its projects can
be checked against it."""
from unittest import mock

from django.test import TestCase
from model_bakery import baker

from app.application.standard_service import StandardService
from app.domain.models import DraftCannotBeEnabled


class StandardEnabledTests(TestCase):
    def test_enabling_a_published_standard_makes_it_runnable(self):
        standard = baker.make("app.Standard", enabled=False, draft=False)

        self.assertTrue(standard.set_enabled(True))
        self.assertTrue(standard.enabled)

    def test_disabling_is_never_runnable(self):
        standard = baker.make("app.Standard", enabled=True, draft=False)

        self.assertFalse(standard.set_enabled(False))
        self.assertFalse(standard.enabled)

    def test_a_draft_cannot_be_enabled_but_can_be_disabled(self):
        draft = baker.make("app.Standard", enabled=True, draft=True)

        with self.assertRaises(DraftCannotBeEnabled):
            draft.set_enabled(True)
        self.assertFalse(draft.set_enabled(False))


class SetEnabledServiceTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        configure = mock.patch("app.application.standard_runs.run_standards.configure")
        configure.start()
        self.addCleanup(configure.stop)

    def test_enabling_queues_the_standard_on_its_projects(self):
        standard = baker.make("app.Standard", tenant=self.tenant, enabled=False, draft=False)
        project = baker.make("app.Project", tenant=self.tenant)
        project.standards.add(standard)

        result = StandardService().set_enabled(self.tenant, None, str(standard.pk), True)

        self.assertTrue(result["enabled"])
        self.assertEqual(result["runs"]["queued"], 1)

    def test_disabling_queues_nothing(self):
        standard = baker.make("app.Standard", tenant=self.tenant, enabled=True, draft=False)

        result = StandardService().set_enabled(self.tenant, None, str(standard.pk), False)

        self.assertFalse(result["enabled"])
        self.assertIsNone(result["runs"])
