from pathlib import Path

import yaml
from django.core.management.base import BaseCommand

from app.domain.models import MarketplacePack, MarketplaceStandard

CONTENT_FIELDS = ("name", "description", "code", "criteria", "test_cases", "suggested_labels", "author")


class Command(BaseCommand):
    help = "Seed marketplace standards and packs from YAML fixtures"

    def handle(self, *args, **options):
        fixtures_dir = (
            Path(__file__).resolve().parent.parent.parent
            / "fixtures"
            / "marketplace"
        )

        # Load standards
        standards_dir = fixtures_dir / "standards"
        loaded = 0
        for yaml_file in sorted(standards_dir.glob("*.yaml")):
            data = yaml.safe_load(yaml_file.read_text())
            slug = data.pop("slug")
            data.pop("version", None)  # version is managed by the seed script, not the fixture

            existing = MarketplaceStandard.objects.filter(slug=slug).first()

            if existing is None:
                mp = MarketplaceStandard.objects.create(slug=slug, version=1, **data)
                self.stdout.write(f"  Created: {mp.name} v{mp.version}")
            else:
                changed = any(
                    getattr(existing, field) != data.get(field)
                    for field in CONTENT_FIELDS
                    if field in data
                )
                if changed:
                    for key, value in data.items():
                        setattr(existing, key, value)
                    existing.version += 1
                    existing.save()
                    self.stdout.write(f"  Updated: {existing.name} v{existing.version}")
                else:
                    self.stdout.write(f"  Unchanged: {existing.name} v{existing.version}")

            loaded += 1

        # Load packs
        packs_file = fixtures_dir / "packs.yaml"
        if packs_file.exists():
            packs_data = yaml.safe_load(packs_file.read_text())
            for pack_data in packs_data:
                standard_slugs = pack_data.pop("standards", [])
                slug = pack_data.pop("slug")
                pack, created = MarketplacePack.objects.update_or_create(
                    slug=slug, defaults=pack_data
                )
                standards = MarketplaceStandard.objects.filter(slug__in=standard_slugs)
                pack.standards.set(standards)
                verb = "Created" if created else "Updated"
                self.stdout.write(f"  {verb} pack: {pack.name} ({standards.count()} standards)")

        self.stdout.write(self.style.SUCCESS(f"\nDone. {loaded} standards loaded."))
