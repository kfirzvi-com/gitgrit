from app.domain.models import Policy, PolicyLabel, PolicyVersion, Tenant, User
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
        except Policy.DoesNotExist:
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
        except Policy.DoesNotExist:
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
        except Policy.DoesNotExist:
            raise ValueError(f"Policy {policy_id} not found")
        policy.delete()
