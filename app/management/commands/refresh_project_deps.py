"""Trigger LLM dependency inference for projects.

  manage.py refresh_project_deps --all          # enqueue all projects
  manage.py refresh_project_deps <id> [<id> ...] # enqueue specific projects
  manage.py refresh_project_deps --all --sync    # run inline (no worker needed)
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from app.domain.models import Project
from app.tasks import infer_project_dependencies


class Command(BaseCommand):
    help = "Enqueue (or run) LLM dependency inference for projects."

    def add_arguments(self, parser):
        parser.add_argument("project_ids", nargs="*", help="Project IDs to refresh")
        parser.add_argument("--all", action="store_true", help="All projects")
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run inline now instead of enqueuing (no worker needed)",
        )

    def handle(self, *args, **opts):
        if opts["all"]:
            projects = list(Project.objects.all())
        elif opts["project_ids"]:
            projects = list(Project.objects.filter(pk__in=opts["project_ids"]))
        else:
            raise CommandError("Pass project IDs or --all")

        if not projects:
            self.stdout.write("No matching projects.")
            return

        for p in projects:
            if opts["sync"]:
                from app.application.dependency_agent import infer_and_store

                Project.objects.filter(pk=p.pk).update(
                    deps_status=Project.DepsStatus.RUNNING, deps_error=""
                )
                try:
                    result = infer_and_store(p)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✓ {p.name}: {len(result.internal)} internal, "
                            f"{len(result.external)} external"
                        )
                    )
                except Exception as exc:
                    Project.objects.filter(pk=p.pk).update(
                        deps_status=Project.DepsStatus.FAILED, deps_error=str(exc)[:2000]
                    )
                    self.stderr.write(self.style.ERROR(f"✗ {p.name}: {exc}"))
            else:
                Project.objects.filter(pk=p.pk).update(
                    deps_status=Project.DepsStatus.PENDING
                )
                infer_project_dependencies.configure(
                    lock=f"project:{p.pk}",
                    queueing_lock=f"deps:{p.pk}",
                ).defer(project_id=str(p.pk))
                self.stdout.write(f"→ queued {p.name}")

        self.stdout.write(self.style.SUCCESS(f"Done ({len(projects)} projects)."))
