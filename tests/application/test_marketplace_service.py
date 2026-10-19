"""Installing from the marketplace copies a standard into the workspace once.

A copy is an ordinary enabled standard that remembers its marketplace source
and version, with the suggested labels; installing again returns the copy
already there, and a pack installs only what the workspace doesn't have."""
from django.test import TestCase
from model_bakery import baker

from app.application import marketplace_service
from app.application.errors import NotFoundError
from app.domain.models import Standard, StandardVersion


class MarketplaceServiceTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.user = baker.make("app.User")
        self.readme = baker.make(
            "app.MarketplaceStandard", slug="readme-exists", name="README Exists",
            code="def evaluate(project):\n    return {}\n", version=2,
            suggested_labels=["documentation"],
        )
        self.license = baker.make(
            "app.MarketplaceStandard", slug="license-file", name="License File",
            code="def evaluate(project):\n    return {}\n", version=1, suggested_labels=[],
        )
        self.pack = baker.make("app.MarketplacePack", slug="repo-hygiene", name="Repository Hygiene")
        self.pack.standards.set([self.readme, self.license])

    def test_installing_copies_the_standard_enabled_with_its_source_and_labels(self):
        standard, created = marketplace_service.install_standard(self.tenant, self.user, "readme-exists")

        self.assertTrue(created)
        self.assertEqual(standard.tenant, self.tenant)
        self.assertEqual(standard.code, self.readme.code)
        self.assertEqual(standard.source_marketplace_standard, self.readme)
        self.assertEqual(standard.source_version, 2)
        self.assertTrue(standard.enabled)
        self.assertFalse(standard.draft)
        self.assertEqual(list(standard.labels.values_list("name", flat=True)), ["documentation"])
        self.assertTrue(StandardVersion.objects.filter(standard=standard).exists())

    def test_installing_twice_returns_the_existing_copy(self):
        first, _ = marketplace_service.install_standard(self.tenant, self.user, "readme-exists")

        again, created = marketplace_service.install_standard(self.tenant, self.user, "readme-exists")

        self.assertFalse(created)
        self.assertEqual(again, first)
        self.assertEqual(Standard.objects.filter(tenant=self.tenant).count(), 1)

    def test_a_pack_installs_only_what_the_workspace_lacks(self):
        existing, _ = marketplace_service.install_standard(self.tenant, self.user, "readme-exists")

        result = marketplace_service.install_pack(self.tenant, self.user, "repo-hygiene")

        self.assertEqual(result["pack"], self.pack)
        self.assertEqual([s.name for s in result["installed"]], ["License File"])
        self.assertEqual(result["skipped"], [existing])

    def test_another_workspace_gets_its_own_copy(self):
        marketplace_service.install_standard(self.tenant, self.user, "readme-exists")
        other = baker.make("app.Tenant")

        _, created = marketplace_service.install_standard(other, self.user, "readme-exists")

        self.assertTrue(created)

    def test_updating_brings_the_copy_to_the_marketplace_version(self):
        standard, _ = marketplace_service.install_standard(self.tenant, self.user, "readme-exists")
        Standard.objects.filter(pk=standard.pk).update(source_version=1, code="old")
        self.assertTrue(
            marketplace_service.update_available(Standard.objects.get(pk=standard.pk), self.readme)
        )

        updated, _ = marketplace_service.update_standard(self.tenant, self.user, "readme-exists")

        self.assertEqual(updated.source_version, 2)
        self.assertEqual(updated.code, self.readme.code)
        self.assertFalse(marketplace_service.update_available(updated, self.readme))

    def test_unknown_slugs_and_uninstalled_updates_are_not_found(self):
        with self.assertRaises(NotFoundError):
            marketplace_service.install_standard(self.tenant, self.user, "nope")
        with self.assertRaises(NotFoundError):
            marketplace_service.install_pack(self.tenant, self.user, "nope")
        with self.assertRaises(NotFoundError):
            marketplace_service.update_standard(self.tenant, self.user, "license-file")
