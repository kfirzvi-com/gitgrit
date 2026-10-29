"""Trigger dependency inference for projects.

  manage.py refresh_project_deps --all          # enqueue all projects
  manage.py refresh_project_deps <id> [<id> ...] # enqueue specific projects
  manage.py refresh_project_deps --all --sync    # run inline (no worker needed)

Local development without a platform connection or an LLM key:

  # read the repository from a checkout on disk instead of the GitHub API
  manage.py refresh_project_deps <id> --local-path ../gitgrit-demo-monorepo
  # take the topology from a fixture instead of asking a model
  manage.py refresh_project_deps <id> --local-path ../repo --fixture topology.json

Both imply --sync and one project.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from app.domain.models import Project
from app.tasks import infer_project_dependencies


class Command(BaseCommand):
    help = "Enqueue (or run) dependency inference for projects."

    def add_arguments(self, parser):
        parser.add_argument("project_ids", nargs="*", help="Project IDs to refresh")
        parser.add_argument("--all", action="store_true", help="All projects")
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run inline now instead of enqueuing (no worker needed)",
        )
        parser.add_argument(
            "--local-path",
            help="Read the repository from this directory instead of the platform API (implies --sync)",
        )
        parser.add_argument(
            "--fixture",
            help="Take the topology from this JSON file instead of running a model (implies --sync)",
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

        local = opts.get("local_path") or opts.get("fixture")
        if local and len(projects) != 1:
            raise CommandError("--local-path / --fixture apply to exactly one project")
        sync = opts["sync"] or bool(local)

        for p in projects:
            if sync:
                self._run_inline(p, opts)
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

    def _run_inline(self, project, opts):
        from app.application.dependency_agent import infer_and_store

        kwargs = {}
        if opts.get("local_path"):
            from app.infrastructure.topology.snapshots import LocalDirSnapshot

            kwargs["snapshot"] = LocalDirSnapshot(opts["local_path"])
        if opts.get("fixture"):
            from app.infrastructure.topology.fake import FakeTopologyInference

            kwargs["inference"] = FakeTopologyInference.from_file(opts["fixture"])

        Project.objects.filter(pk=project.pk).update(
            deps_status=Project.DepsStatus.RUNNING, deps_error=""
        )
        try:
            summary = infer_and_store(project, **kwargs)
        except Exception as exc:
            Project.objects.filter(pk=project.pk).update(
                deps_status=Project.DepsStatus.FAILED, deps_error=str(exc)[:2000]
            )
            self.stderr.write(self.style.ERROR(f"✗ {project.name}: {exc}"))
            return
        shape = ""
        if summary.created or summary.removed:
            shape = f" (components +{len(summary.created)}/-{len(summary.removed)})"
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ {project.name}: {summary.components} components{shape}, "
                f"{summary.internal} internal, {summary.infrastructure} infra, "
                f"{summary.external} external, {summary.files_read} files read"
            )
        )
        for target in summary.unresolved:
            self.stdout.write(f"  ? unresolved internal target: {target}")
