from django.core.exceptions import ValidationError

from app.domain.models import PolicyExecution, Project, Tenant
from app.domain.policy_criteria import score_to_grade


class ProjectStatusService:
    def get_project_status(self, tenant: Tenant, project_id: str) -> dict:
        """Return an at-a-glance compliance snapshot for a project.

        Aggregates the *latest* execution per policy (DISTINCT ON in Postgres —
        safe here because the stack is Postgres-only) so a policy run many
        times does not skew the average.
        """
        try:
            project = Project.objects.get(tenant=tenant, id=project_id)
        except (Project.DoesNotExist, ValidationError):
            raise ValueError(f"Project {project_id} not found")

        latest = list(
            PolicyExecution.objects.filter(
                project=project,
                policy__isnull=False,
                status__in=[
                    PolicyExecution.Status.PASSED,
                    PolicyExecution.Status.FAILED,
                ],
            )
            .order_by("policy_id", "-created_at")
            .distinct("policy_id")
        )

        scores = [e.score for e in latest if e.score is not None]
        overall = sum(scores) / len(scores) if scores else None
        top_offenders = sorted(latest, key=lambda e: e.score or 0)[:3]

        return {
            "project": {"id": str(project.id), "name": project.name},
            "overall_score": overall,
            "grade": score_to_grade(overall),
            "total_policies": len(latest),
            "passed": sum(
                1 for e in latest if e.status == PolicyExecution.Status.PASSED
            ),
            "failed": sum(
                1 for e in latest if e.status == PolicyExecution.Status.FAILED
            ),
            "top_offenders": [
                {
                    "policy_id": str(e.policy_id),
                    "name": e.policy_name,
                    "score": e.score,
                    "message": e.message,
                    "last_run": e.created_at.isoformat(),
                }
                for e in top_offenders
            ],
        }
