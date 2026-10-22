# A commit reads its newest check alone: a check's score comes from its own
# runs, never filled in from an earlier check's
# (app.domain.scoring.ScorableCommitCheck.new_commit_score). Every saved score
# is re-decided from its own check's runs, and every finished check that never
# saved one (it was "incomplete" before) gets one, so each commit reads its
# newest check. The rule is copied here, frozen, so later changes to the
# domain never change what this migration does.

from django.db import migrations

WEIGHT = {"required": 2, "major": 2, "minor": 1}
FINISHED = ("passed", "failed", "error")
REMOVED_STANDARD = "a removed standard"


def decide(runs, not_run):
    """(value, failed, reason) for a check's finished runs and the names of
    the standards it expected that never finished in it."""
    missing = [f"{r.standard_name} errored" for r in runs if r.status == "error"]
    missing += [f"{name} not run" for name in not_run]
    if missing:
        return None, False, ", ".join(missing)
    failing = [r for r in runs if r.importance == "required" and r.status == "failed"]
    if failing:
        return None, True, ", ".join(r.standard_name for r in failing) + " failing"
    total = sum(WEIGHT.get(r.importance, 2) for r in runs)
    if not total:
        return None, False, ""
    return round(sum(r.score * WEIGHT.get(r.importance, 2) for r in runs) / total), False, ""


def own_results(check):
    """Each expected standard's newest finished run in ``check``, and the
    expected ones with none."""
    expected = [str(i) for i in check.expected_standard_ids]
    picked = {}
    for run in check.executions.order_by("-created_at"):
        key = str(run.standard_id)
        if run.status in FINISHED and key in expected and key not in picked:
            picked[key] = run
    return list(picked.values()), [i for i in expected if i not in picked]


def rescore(apps, schema_editor):
    CommitCheck = apps.get_model("app", "CommitCheck")
    CommitScore = apps.get_model("app", "CommitScore")
    Standard = apps.get_model("app", "Standard")
    names = dict((str(pk), name) for pk, name in Standard._base_manager.values_list("pk", "name"))

    for check in CommitCheck.objects.exclude(commit_sha="").iterator(chunk_size=500):
        # Nothing to decide without expectations, or while a run goes.
        if not check.expected_standard_ids or check.executions.filter(status="running").exists():
            continue
        runs, never_finished = own_results(check)
        value, failed, reason = decide(runs, [names.get(i, REMOVED_STANDARD) for i in never_finished])
        scores = list(CommitScore.objects.filter(commit_check=check))
        if not scores:
            scores = [
                CommitScore.objects.create(
                    project_id=check.project_id,
                    commit_check=check,
                    branch=check.branch,
                    commit_sha=check.commit_sha,
                    committed_at=check.committed_at,
                    ordered_at=check.committed_at or check.created_at,
                    value=value,
                    failed=failed,
                    reason=reason,
                )
            ]
        for score in scores:
            score.value, score.failed, score.reason = value, failed, reason
            score.save(update_fields=["value", "failed", "reason"])
            score.executions.set(runs)


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0056_rescore_commit_scores_no_score_first"),
    ]

    operations = [
        migrations.RunPython(rescore, migrations.RunPython.noop),
    ]
