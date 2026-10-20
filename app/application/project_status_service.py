from django.core.exceptions import ValidationError

from app.application.errors import NotFoundError
from app.application.grading_service import grade_for_project
from app.domain.models import Project, StandardExecution, Tenant


class ProjectStatusService:
    def get_project_status(
        self, tenant: Tenant, project_id: str, exclude_execution_ids=()
    ) -> dict:
        """Return an at-a-glance compliance snapshot for a project.

        ``grade`` is the letter the project page shows (``None`` when nothing
        is evaluated yet) and ``reason`` its one-sentence explanation, both
        from ``grade_for_project``: the latest counting result per attached,
        enabled, non-draft standard on that standard's home branch (see
        ``app.application.standard_results``), so a standard run many times
        does not skew the picture and runs on other branches do not move it.
        ``overall_score`` (the mean of those results' scores) stays for
        clients that read it. ``top_offenders`` are the results that did not
        pass, critical first, then failed before errored, lowest score first
        within each. ``exclude_execution_ids`` leaves those executions out,
        which gives the project's picture as it was before a run.
        """
        try:
            project = Project.objects.get(tenant=tenant, id=project_id)
        except (Project.DoesNotExist, ValidationError):
            raise NotFoundError(f"Project {project_id} not found")

        grading_ = grade_for_project(project, exclude_execution_ids=exclude_execution_ids)
        latest = grading_.executions
        critical_ids = grading_.critical_standard_ids

        scores = [e.score for e in latest if e.score is not None]
        overall = sum(scores) / len(scores) if scores else None
        offenders = sorted(
            (e for e in latest if e.status != StandardExecution.Status.PASSED),
            key=lambda e: (
                e.standard_id not in critical_ids,
                e.status != StandardExecution.Status.FAILED,
                e.score or 0,
            ),
        )[:3]

        grade = grading_.grade
        return {
            "project": {"id": str(project.id), "name": project.name},
            "overall_score": overall,
            "grade": grade.letter if grade.graded else None,
            "reason": grade.reason,
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
                    "critical": e.standard_id in critical_ids,
                    "status": e.status,
                    "score": e.score,
                    "message": e.message,
                    "last_run": e.created_at.isoformat(),
                }
                for e in offenders
            ],
        }
