"""Diagnose LLM model discovery for one API key: which models the catalog
lists, and what each access probe answered.

    GEMINI_KEY=... python manage.py probe_llm_models gemini --api-key-env GEMINI_KEY

Prints one line per model (verdict, HTTP status, model, provider error text)
so a wrong verdict can be traced to the exact response. Same code path as
"Add provider" / "fetch", including the 20s budget unless --budget is given.
"""
import os
import time

from django.core.management.base import BaseCommand, CommandError

from app.domain.models import LLMProviderType
from app.infrastructure.llm_models import PROBE_BUDGET, fetch_catalog, probe_models


class Command(BaseCommand):
    help = "Probe every model a provider lists and show which ones this key can use."

    def add_arguments(self, parser):
        parser.add_argument("provider_type", choices=LLMProviderType.values)
        parser.add_argument(
            "--api-key-env",
            required=True,
            help="Name of the environment variable holding the API key "
            "(keeps the key out of shell history and transcripts).",
        )
        parser.add_argument("--base-url", default="")
        parser.add_argument(
            "--budget", type=float, default=PROBE_BUDGET,
            help=f"Seconds for the whole batch (default {PROBE_BUDGET:.0f}, as in the UI).",
        )
        parser.add_argument(
            "--detail", type=int, default=160, help="Max chars of error text per line."
        )

    def handle(self, *args, **opts):
        api_key = os.environ.get(opts["api_key_env"], "")
        if not api_key:
            raise CommandError(f"environment variable {opts['api_key_env']} is empty")

        started = time.monotonic()
        catalog = fetch_catalog(opts["provider_type"], opts["base_url"], api_key)
        self.stdout.write(
            f"catalog: {len(catalog)} models in {time.monotonic() - started:.1f}s"
        )
        if not catalog:
            return

        started = time.monotonic()
        results = probe_models(
            opts["provider_type"], opts["base_url"], api_key, catalog, budget=opts["budget"]
        )
        width = max(len(r.model) for r in results)
        for r in results:
            self.stdout.write(
                f"{r.label:<8} {str(r.status or '-'):>4}  {r.model:<{width}}  "
                f"{r.detail[: opts['detail']]}"
            )
        counts = {k: sum(1 for r in results if r.label == k) for k in ("usable", "rejected", "unknown")}
        self.stdout.write(
            f"\n{counts['usable']} usable, {counts['rejected']} rejected, "
            f"{counts['unknown']} unknown (kept) in {time.monotonic() - started:.1f}s"
        )
