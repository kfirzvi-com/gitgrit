from pathlib import Path

import yaml
from django.core.management.base import BaseCommand

from app.domain.models import MarketplacePack, MarketplacePolicy

CONTENT_FIELDS = ("name", "description", "code", "criteria", "test_cases", "suggested_labels", "author")


class Command(BaseCommand):
    help = "Seed marketplace policies and packs from YAML fixtures"

    def handle(self, *args, **options):
        fixtures_dir = (
            Path(__file__).resolve().parent.parent.parent
            / "fixtures"
            / "marketplace"
        )

        # Load policies
        policies_dir = fixtures_dir / "policies"
        loaded = 0
        for yaml_file in sorted(policies_dir.glob("*.yaml")):
            data = yaml.safe_load(yaml_file.read_text())
            slug = data.pop("slug")
            data.pop("version", None)  # version is managed by the seed script, not the fixture

            existing = MarketplacePolicy.objects.filter(slug=slug).first()

            if existing is None:
                mp = MarketplacePolicy.objects.create(slug=slug, version=1, **data)
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
                policy_slugs = pack_data.pop("policies", [])
                slug = pack_data.pop("slug")
                pack, created = MarketplacePack.objects.update_or_create(
                    slug=slug, defaults=pack_data
                )
                policies = MarketplacePolicy.objects.filter(slug__in=policy_slugs)
                pack.policies.set(policies)
                verb = "Created" if created else "Updated"
                self.stdout.write(f"  {verb} pack: {pack.name} ({policies.count()} policies)")

        self.stdout.write(self.style.SUCCESS(f"\nDone. {loaded} policies loaded."))
