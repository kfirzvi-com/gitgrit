"""Bet 2 of the grade gate: the neglect clock on each attachment.

Adds ``ProjectStandard.first_failed_at`` and starts the clock, at migration
time, for every attachment that is failing right now: the clock never
counts days before the release, so nobody is capped on day one. "Failing"
is decided by the same rules the grade reads with (see
``app.application.standard_results.current_results`` and
``app.application.grading_service``), written here with the migration-state
ORM so this file never imports app code: the attachment's latest finished
execution on the standard's home branch (the branch its Branch/Tag Filter
names literally, else the project's default branch; a manual run with an
empty ref reads the default branch), newest commit first, skipping running,
skipped and platform-origin error rows, where the standard is enabled and
not a draft, and that row is failed or a standard-origin error.
"""

import re

from django.db import migrations, models
from django.db.models.functions import Coalesce
from django.utils import timezone

# Mirrors the engine's values; a migration pins them rather than importing.
RUNNING = "running"
SKIPPED = "skipped"
FAILED = "failed"
ERROR = "error"
PLATFORM_ORIGIN = "platform"

# ``standard_engine.literal_ref``: a Branch/Tag Filter names a branch
# literally unless it is empty or a regex.
_REGEX_CHARS = re.compile(r"[*+?()\[\]{}|\\]")


def literal_ref(pattern):
    name = (pattern or "").strip().removeprefix("^").removesuffix("$")
    if not name or _REGEX_CHARS.search(name):
        return ""
    return name


def home_branch(project, standard):
    criteria = standard.criteria or {}
    return literal_ref(criteria.get("ref")) or project.default_branch


def latest_counting_status(StandardExecution, attachment):
    """The status of the attachment's latest counting execution, or None."""
    home = home_branch(attachment.project, attachment.standard)
    refs = [home, f"refs/heads/{home}"]
    if home == attachment.project.default_branch:
        refs.append("")
    committed = Coalesce("commit_check__committed_at", "created_at")
    return (
        StandardExecution.objects.filter(
            project_id=attachment.project_id,
            standard_id=attachment.standard_id,
            ref__in=refs,
        )
        .exclude(status__in=[RUNNING, SKIPPED])
        .exclude(status=ERROR, error_origin=PLATFORM_ORIGIN)
        .order_by(committed.desc(), "-created_at")
        .values_list("status", flat=True)
        .first()
    )


def start_clocks_for_failing_attachments(apps, schema_editor):
    ProjectStandard = apps.get_model("app", "ProjectStandard")
    StandardExecution = apps.get_model("app", "StandardExecution")
    now = timezone.now()
    failing = [
        attachment.pk
        for attachment in ProjectStandard.objects.filter(
            standard__enabled=True, standard__draft=False
        ).select_related("project", "standard")
        if latest_counting_status(StandardExecution, attachment) in (FAILED, ERROR)
    ]
    ProjectStandard.objects.filter(pk__in=failing).update(first_failed_at=now)


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0048_critical_marks"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectstandard",
            name="first_failed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(
            start_clocks_for_failing_attachments, migrations.RunPython.noop
        ),
    ]
