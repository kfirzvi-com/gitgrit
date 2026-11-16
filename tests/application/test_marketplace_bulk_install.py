"""Installing or updating many Marketplace standards at once."""
from django.test import TestCase
from model_bakery import baker

from app.application.marketplace_bulk_install import MarketplaceBulkInstall

class MarketplaceBulkInstallTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.lint = baker.make("app.MarketplaceStandard", slug="lint", name="Lint", version=2, code="x = 1")
        self.docs = baker.make("app.MarketplaceStandard", slug="docs", name="Docs", version=1, code="x = 1")
        self.edit = MarketplaceBulkInstall(self.tenant, baker.make("app.User"))

    def test_installing_counts_those_already_there(self):
        self.edit.apply("install", [self.lint.pk])

        result = self.edit.apply("install", [self.lint.pk, self.docs.pk])

        assert (result.changed, result.unchanged) == (1, 1)
        assert set(self.tenant.standards.values_list("name", flat=True)) == {"Lint", "Docs"}

    def test_updating_skips_those_not_installed_and_brings_the_rest_to_the_newest(self):
        self.edit.apply("install", [self.lint.pk])
        copy = self.tenant.standards.get(name="Lint")
        copy.source_version = 1
        copy.save(update_fields=["source_version"])

        result = self.edit.apply("update", [self.lint.pk, self.docs.pk])

        copy.refresh_from_db()
        assert (result.changed, result.skipped) == (1, 1)
        assert copy.source_version == 2
