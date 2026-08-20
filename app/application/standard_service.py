from django.core.exceptions import ValidationError

from app.application.event_bus import publish
from app.domain.events import StandardSaved
from app.domain.models import Standard, StandardLabel, StandardVersion, Project, Tenant, User
from app.domain.standard_criteria import language_matches
from app.domain.standard_extractor import extract_rules, to_dict
from app.domain.standard_validator import validate_standard_code

_DEFAULT_CODE = 'def evaluate(project):\n    return {"passed": True, "score": 100, "message": "OK", "details": {}}\n'


def create_standard_version(standard: Standard, user: User, summary: str) -> dict | None:
    """Snapshot the standard's current state as an immutable version.

    Every definition mutation (web forms, MCP tools, revert) funnels through
    here, which makes it the coverage-change choke point: after the snapshot,
    a runnable standard is re-run on its linked projects via ``StandardSaved``.
    Returns the run summary for user feedback, or None when nothing ran.
    """
    latest = (
        StandardVersion.objects.filter(standard=standard)
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
    )
    version_num = (latest or 0) + 1
    StandardVersion.objects.create(
        standard=standard,
        version=version_num,
        code=standard.code,
        description=standard.description,
        criteria=standard.criteria,
        test_cases=standard.test_cases,
        labels_snapshot=list(standard.labels.values_list("name", flat=True)),
        changed_by=user,
        change_summary=summary,
    )
    if not (standard.enabled and not standard.draft):
        return None
    results = publish(
        StandardSaved(
            standard_id=str(standard.id), tenant_id=str(standard.tenant_id)
        )
    )
    return results[0] if results else None


class StandardService:
    def list_standards(self, tenant: Tenant) -> list[dict]:
        return [
            {
                "id": str(p.id),
                "name": p.name,
                "description": p.description,
                "enabled": p.enabled,
                "draft": p.draft,
                "labels": [lbl.name for lbl in p.labels.all()],
                "events": p.criteria.get("events", []),
                "ref_pattern": p.criteria.get("ref", ""),
                "languages": p.criteria.get("languages", []),
                "created_at": p.created_at.isoformat(),
                "updated_at": p.updated_at.isoformat(),
            }
            for p in Standard.objects.filter(tenant=tenant).prefetch_related("labels")
        ]

    def get_standard(self, tenant: Tenant, standard_id: str) -> dict:
        try:
            p = Standard.objects.prefetch_related("labels").get(id=standard_id, tenant=tenant)
        except (Standard.DoesNotExist, ValidationError):
            raise ValueError(f"Standard {standard_id} not found")

        recent_executions = list(
            p.executions.order_by("-created_at")[:5].select_related("project")
        )
        return {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "code": p.code,
            "enabled": p.enabled,
            "draft": p.draft,
            "labels": [lbl.name for lbl in p.labels.all()],
            "criteria": p.criteria,
            "test_cases": p.test_cases,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
            "recent_executions": [
                {
                    "status": e.status,
                    "score": e.score,
                    "message": e.message,
                    "project": e.project.name,
                    "created_at": e.created_at.isoformat(),
                }
                for e in recent_executions
            ],
        }

    def create_standard(self, tenant: Tenant, user: User, data: dict) -> dict:
        validate_standard_code(data.get("code", _DEFAULT_CODE))
        label_names = data.get("labels", [])
        standard = Standard.objects.create(
            tenant=tenant,
            name=data["name"],
            code=data.get("code", _DEFAULT_CODE),
            description=data.get("description", ""),
            draft=data.get("draft", False),
            criteria={
                "events": data.get("events", []),
                "ref": data.get("ref_pattern", ""),
                "languages": data.get("languages", []),
            },
        )
        labels = []
        for name in label_names:
            lbl, _ = StandardLabel.objects.get_or_create(tenant=tenant, name=name)
            labels.append(lbl)
        if labels:
            standard.labels.set(labels)
        runs = create_standard_version(standard, user, data.get("change_summary", "Created"))
        result = {"id": str(standard.id), "name": standard.name, "created": True}
        if runs:
            result["runs"] = runs
        return result

    def update_standard(self, tenant: Tenant, user: User, standard_id: str, data: dict) -> dict:
        try:
            standard = Standard.objects.prefetch_related("labels").get(id=standard_id, tenant=tenant)
        except (Standard.DoesNotExist, ValidationError):
            raise ValueError(f"Standard {standard_id} not found")

        change_summary = data.get("change_summary", "Updated")
        update_fields = ["updated_at"]

        if "name" in data:
            standard.name = data["name"]
            update_fields.append("name")
        if "code" in data:
            validate_standard_code(data["code"])
            standard.code = data["code"]
            update_fields.append("code")
        if "description" in data:
            standard.description = data["description"]
            update_fields.append("description")
        if "draft" in data:
            standard.draft = data["draft"]
            update_fields.append("draft")

        criteria = dict(standard.criteria)
        criteria_changed = False
        if "events" in data:
            criteria["events"] = data["events"]
            criteria_changed = True
        if "ref_pattern" in data:
            criteria["ref"] = data["ref_pattern"]
            criteria_changed = True
        if "languages" in data:
            criteria["languages"] = data["languages"]
            criteria_changed = True
        if criteria_changed:
            standard.criteria = criteria
            update_fields.append("criteria")

        standard.save(update_fields=update_fields)

        if "labels" in data:
            labels = []
            for name in data["labels"]:
                lbl, _ = StandardLabel.objects.get_or_create(tenant=tenant, name=name)
                labels.append(lbl)
            standard.labels.set(labels)

        runs = create_standard_version(standard, user, change_summary)
        result = {"id": str(standard.id), "name": standard.name, "updated": True}
        if runs:
            result["runs"] = runs
        return result

    def delete_standard(self, tenant: Tenant, standard_id: str) -> None:
        try:
            standard = Standard.objects.get(id=standard_id, tenant=tenant)
        except (Standard.DoesNotExist, ValidationError):
            raise ValueError(f"Standard {standard_id} not found")
        standard.delete()

    def list_active_for_project(
        self, tenant: Tenant, project_id: str
    ) -> list[dict]:
        """Return the active, non-draft standards attached to a project.

        Only standards attached to the project are considered — a workspace
        standard that is not attached does not apply, no matter its criteria.

        Shape is tailored for client-side enforcement: each standard carries a
        ``rules`` block produced by :func:`app.domain.standard_extractor.extract_rules`
        (watched files, kind-tagged forbidden patterns, a local-enforceability
        flag, and per-dimension completeness flags). Raw source is not shipped.

        Event and ref-pattern criteria are intentionally ignored — those are
        webhook-time filters. Language match is the only applicability gate
        within the attached set.
        """
        try:
            project = Project.objects.get(tenant=tenant, id=project_id)
        except (Project.DoesNotExist, ValidationError):
            raise ValueError(f"Project {project_id} not found")

        standards = project.standards.filter(
            enabled=True, draft=False
        ).prefetch_related("labels")

        result = []
        for standard in standards:
            criteria = standard.criteria or {}
            if not language_matches(
                criteria.get("languages", []), project.languages or []
            ):
                continue

            last_exec = (
                standard.executions.filter(project=project)
                .order_by("-created_at")
                .first()
            )

            result.append(
                {
                    "id": str(standard.id),
                    "name": standard.name,
                    "description": standard.description,
                    "rules": to_dict(extract_rules(standard.code)),
                    "enabled": standard.enabled,
                    "draft": standard.draft,
                    "labels": [lbl.name for lbl in standard.labels.all()],
                    "languages": criteria.get("languages", []),
                    "last_execution": {
                        "score": last_exec.score,
                        "status": last_exec.status,
                        "message": last_exec.message,
                        "created_at": last_exec.created_at.isoformat(),
                    }
                    if last_exec
                    else None,
                }
            )
        return result
