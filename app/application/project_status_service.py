from django.core.exceptions import ValidationError

from app.domain.models import StandardExecution, Project, Tenant
from app.domain.standard_criteria import score_to_grade


class ProjectStatusService:
    def get_project_status(self, tenant: Tenant, project_id: str) -> dict:
        """Return an at-a-glance compliance snapshot for a project.

        Aggregates the *latest* execution per standard (DISTINCT ON in Postgres —
        safe here because the stack is Postgres-only) so a standard run many
        times does not skew the average. Only standards currently attached to
        the project count — detaching a standard removes its history from the
        score.
        """
        try:
            project = Project.objects.get(tenant=tenant, id=project_id)
        except (Project.DoesNotExist, ValidationError):
            raise ValueError(f"Project {project_id} not found")

        latest = list(
            StandardExecution.objects.filter(
                project=project,
                standard__in=project.standards.all(),
                status__in=[
                    StandardExecution.Status.PASSED,
                    StandardExecution.Status.FAILED,
                ],
            )
            .order_by("standard_id", "-created_at")
            .distinct("standard_id")
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
