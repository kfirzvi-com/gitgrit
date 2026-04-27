from django.core.exceptions import ValidationError

from app.domain.models import Policy, PolicyLabel, PolicyVersion, Project, Tenant, User
from app.domain.policy_criteria import language_matches
from app.domain.policy_extractor import extract_rules, to_dict
from app.domain.policy_validator import validate_policy_code

_DEFAULT_CODE = 'def evaluate(project):\n    return {"passed": True, "score": 100, "message": "OK", "details": {}}\n'


def create_policy_version(policy: Policy, user: User, summary: str) -> PolicyVersion:
    latest = (
        PolicyVersion.objects.filter(policy=policy)
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
    )
    version_num = (latest or 0) + 1
    return PolicyVersion.objects.create(
        policy=policy,
        version=version_num,
        code=policy.code,
        description=policy.description,
        criteria=policy.criteria,
        test_cases=policy.test_cases,
        labels_snapshot=list(policy.labels.values_list("name", flat=True)),
        changed_by=user,
        change_summary=summary,
    )


class PolicyService:
    def list_policies(self, tenant: Tenant) -> list[dict]:
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
            for p in Policy.objects.filter(tenant=tenant).prefetch_related("labels")
        ]

    def get_policy(self, tenant: Tenant, policy_id: str) -> dict:
        try:
            p = Policy.objects.prefetch_related("labels").get(id=policy_id, tenant=tenant)
        except (Policy.DoesNotExist, ValidationError):
            raise ValueError(f"Policy {policy_id} not found")

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

    def create_policy(self, tenant: Tenant, user: User, data: dict) -> dict:
        validate_policy_code(data.get("code", _DEFAULT_CODE))
        label_names = data.get("labels", [])
        policy = Policy.objects.create(
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
            lbl, _ = PolicyLabel.objects.get_or_create(tenant=tenant, name=name)
            labels.append(lbl)
        if labels:
            policy.labels.set(labels)
        create_policy_version(policy, user, data.get("change_summary", "Created"))
        return {"id": str(policy.id), "name": policy.name, "created": True}

    def update_policy(self, tenant: Tenant, user: User, policy_id: str, data: dict) -> dict:
        try:
            policy = Policy.objects.prefetch_related("labels").get(id=policy_id, tenant=tenant)
        except (Policy.DoesNotExist, ValidationError):
            raise ValueError(f"Policy {policy_id} not found")

        change_summary = data.get("change_summary", "Updated")
        update_fields = ["updated_at"]

        if "name" in data:
            policy.name = data["name"]
            update_fields.append("name")
        if "code" in data:
            validate_policy_code(data["code"])
            policy.code = data["code"]
            update_fields.append("code")
        if "description" in data:
            policy.description = data["description"]
            update_fields.append("description")
        if "draft" in data:
            policy.draft = data["draft"]
            update_fields.append("draft")

        criteria = dict(policy.criteria)
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
            policy.criteria = criteria
            update_fields.append("criteria")

        policy.save(update_fields=update_fields)

        if "labels" in data:
            labels = []
            for name in data["labels"]:
                lbl, _ = PolicyLabel.objects.get_or_create(tenant=tenant, name=name)
                labels.append(lbl)
            policy.labels.set(labels)

        create_policy_version(policy, user, change_summary)
        return {"id": str(policy.id), "name": policy.name, "updated": True}

    def delete_policy(self, tenant: Tenant, policy_id: str) -> None:
        try:
            policy = Policy.objects.get(id=policy_id, tenant=tenant)
        except (Policy.DoesNotExist, ValidationError):
            raise ValueError(f"Policy {policy_id} not found")
        policy.delete()

    def list_active_for_project(
        self, tenant: Tenant, project_id: str
    ) -> list[dict]:
        """Return active, non-draft policies applicable to a project.

        Shape is tailored for client-side enforcement: each policy carries a
        ``rules`` block produced by :func:`app.domain.policy_extractor.extract_rules`
        (watched files, kind-tagged forbidden patterns, a local-enforceability
        flag, and per-dimension completeness flags). Raw source is not shipped.

        Event and ref-pattern criteria are intentionally ignored — those are
        webhook-time filters. Language match is the only applicability gate.
        """
        try:
            project = Project.objects.get(tenant=tenant, id=project_id)
        except (Project.DoesNotExist, ValidationError):
            raise ValueError(f"Project {project_id} not found")

        policies = Policy.objects.filter(
            tenant=tenant, enabled=True, draft=False
        ).prefetch_related("labels")

        result = []
        for policy in policies:
            criteria = policy.criteria or {}
            if not language_matches(
                criteria.get("languages", []), project.languages or []
            ):
                continue

            last_exec = (
                policy.executions.filter(project=project)
                .order_by("-created_at")
                .first()
            )

            result.append(
                {
                    "id": str(policy.id),
                    "name": policy.name,
                    "description": policy.description,
                    "rules": to_dict(extract_rules(policy.code)),
                    "enabled": policy.enabled,
                    "draft": policy.draft,
                    "labels": [lbl.name for lbl in policy.labels.all()],
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
