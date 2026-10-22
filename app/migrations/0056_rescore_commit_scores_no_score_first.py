# Commit scores under the "no score until every standard has a result" rule
# (app.domain.scoring.RequiredGateWeightedAveragePolicy): any standard that
# errored, Required too, leaves the commit without a score, before a failed
# Required standard can fail it. Saved scores are re-decided from the runs they
# were computed from. The rule is copied here, frozen, so later changes to the
# domain never change what this migration does.

from django.db import migrations

WEIGHT = {"required": 2, "major": 2, "minor": 1}


def decide(runs):
    """(value, failed, reason) for a commit's finished runs."""
    errored = [r for r in runs if r.status == "error"]
    if errored:
        return None, False, ", ".join(f"{r.standard_name} errored" for r in errored)
    failing = [r for r in runs if r.importance == "required" and r.status == "failed"]
    if failing:
        return None, True, ", ".join(r.standard_name for r in failing) + " failing"
    total = sum(WEIGHT.get(r.importance, 2) for r in runs)
    if not total:
        return None, False, ""
    return round(sum(r.score * WEIGHT.get(r.importance, 2) for r in runs) / total), False, ""


def rescore(apps, schema_editor):
    CommitScore = apps.get_model("app", "CommitScore")
    for score in CommitScore.objects.prefetch_related("executions").iterator(chunk_size=500):
        runs = [r for r in score.executions.all() if r.status in ("passed", "failed", "error")]
        if not runs:
            continue
        value, failed, reason = decide(runs)
        if (score.value, score.failed, score.reason) != (value, failed, reason):
            score.value, score.failed, score.reason = value, failed, reason
            score.save(update_fields=["value", "failed", "reason"])


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0055_workspace_score_display"),
    ]

    operations = [
        migrations.RunPython(rescore, migrations.RunPython.noop),
    ]
