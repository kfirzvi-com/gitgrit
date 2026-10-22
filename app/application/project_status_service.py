from django.core.exceptions import ValidationError

from app.application import scoring
from app.application.errors import NotFoundError
from app.domain.models import StandardExecution, Project, Tenant
from app.domain.score_representation import COMMIT_SCORE_REPRESENTATION


class ProjectStatusService:
    def get_project_status(
        self, tenant: Tenant, project_id: str, exclude_execution_ids=()
    ) -> dict:
        """Return an at-a-glance compliance snapshot for a project: its score
        (the newest scored commit on its default branch, see
        ``app.application.scoring``) and the results behind it.
        ``exclude_execution_ids`` leaves out a score computed from those
        executions, which gives the project's picture as it was before a run.
        """
        try:
            project = Project.objects.get(tenant=tenant, id=project_id)
        except (Project.DoesNotExist, ValidationError):
            raise NotFoundError(f"Project {project_id} not found")

        score = scoring.project_score(project, excluding=exclude_execution_ids)
        results = list(score.executions.all()) if score else []
        overall = score.value if score else None
        represented = COMMIT_SCORE_REPRESENTATION.represent(overall, failed=bool(score and score.failed))
        top_offenders = sorted(results, key=lambda e: e.score or 0)[:3]

        return {
            "project": {"id": str(project.id), "name": project.name},
            "overall_score": overall,
            "outcome": str(score.outcome) if score else None,
            # The score as the app shows it (COMMIT_SCORE_REPRESENTATION).
            "grade": represented.text,
            "display": represented.as_dict(),
            "score_failed": score.failed if score else False,
            "reason": score.reason if score else "",
            "commit_sha": score.commit_sha if score else None,
            "total_standards": len(results),
            "passed": sum(
                1 for e in results if e.status == StandardExecution.Status.PASSED
            ),
            "failed": sum(
                1 for e in results if e.status == StandardExecution.Status.FAILED
            ),
            "top_offenders": [
                {
                    "standard_id": str(e.standard_id),
                    "name": e.standard_name,
                    "score": e.score,
                    "message": e.message,
                    "last_run": e.created_at.isoformat(),
                }
                for e in top_offenders
            ],
        }
