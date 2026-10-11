from django.core.exceptions import ValidationError

from app.application.standard_results import current_results
from app.domain.models import StandardExecution, Project, Tenant
from app.domain.standard_criteria import score_to_grade


class ProjectStatusService:
    def get_project_status(
        self, tenant: Tenant, project_id: str, exclude_execution_ids=()
    ) -> dict:
        """Return an at-a-glance compliance snapshot for a project.

        Aggregates each attached standard's latest passed or failed result on
        its home branch (see ``app.application.standard_results``), so a
        standard run many times does not skew the average and runs on other
        branches do not move it. ``exclude_execution_ids`` leaves those
        executions out, which gives the project's picture as it was before a
        run.
        """
        try:
            project = Project.objects.get(tenant=tenant, id=project_id)
        except (Project.DoesNotExist, ValidationError):
            raise ValueError(f"Project {project_id} not found")

        latest = current_results(
            [project],
            statuses=(StandardExecution.Status.PASSED, StandardExecution.Status.FAILED),
            exclude_execution_ids=exclude_execution_ids,
        )

        scores = [e.score for e in latest if e.score is not None]
        overall = sum(scores) / len(scores) if scores else None
        top_offenders = sorted(latest, key=lambda e: e.score or 0)[:3]

        return {
            "project": {"id": str(project.id), "name": project.name},
            "overall_score": overall,
            "grade": score_to_grade(overall),
            "total_standards": len(latest),
            "passed": sum(
                1 for e in latest if e.status == StandardExecution.Status.PASSED
            ),
            "failed": sum(
                1 for e in latest if e.status == StandardExecution.Status.FAILED
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
