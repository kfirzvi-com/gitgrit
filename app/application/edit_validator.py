import re
from collections import Counter

from django.core.exceptions import ValidationError

from app.application.policy_service import PolicyService
from app.domain.models import Project, Tenant

_SNIPPET_PADDING = 40


def _normalize_file_path(path: str) -> str:
    return path.lstrip("/").removeprefix("./")


def _matches(content: str, kind: str, value: str) -> list[str]:
    """Return every substring `content` matches for the given forbidden pattern.

    The kinds mirror :class:`app.domain.policy_extractor.PredicateKind`. Returning
    a list (not a set) lets callers do multiset diffs against prior content so
    repeated occurrences are attributed correctly.
    """
    if not content:
        return []
    if kind == "search":
        try:
            return [m.group(0) for m in re.finditer(value, content)]
        except re.error:
            return []
    if kind == "match":
        try:
            m = re.match(value, content)
        except re.error:
            return []
        return [m.group(0)] if m else []
    if kind == "startswith":
        return [value] if content.startswith(value) else []
    if kind == "endswith":
        return [value] if content.endswith(value) else []
    if kind == "in":
        return [value] * content.count(value)
    return []


def _snippet(content: str, needle: str) -> str:
    idx = content.find(needle)
    if idx < 0:
        return needle
    start = max(0, idx - _SNIPPET_PADDING)
    end = min(len(content), idx + len(needle) + _SNIPPET_PADDING)
    body = content[start:end].replace("\n", " ")
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{body}{suffix}"


class EditValidator:
    def __init__(self) -> None:
        self._policies = PolicyService()

    def validate_edit(
        self,
        tenant: Tenant,
        project_id: str,
        file_path: str,
        new_content: str,
        prior_content: str | None = None,
    ) -> dict:
        """Run the project's active policies against a proposed edit.

        Returns introduced violations (multiset diff between new and prior
        content keyed on (policy, kind, value, matched_substring)), a count of
        pre-existing violations that survived the edit, and per-policy notes
        when the extractor saw rules it could not fully parse.
        """
        try:
            Project.objects.get(tenant=tenant, id=project_id)
        except (Project.DoesNotExist, ValidationError):
            raise ValueError(f"Project {project_id} not found")

        normalized_path = _normalize_file_path(file_path)
        active_policies = self._policies.list_active_for_project(tenant, project_id)

        introduced: list[dict] = []
        pre_existing_count = 0
        notes: list[str] = []
        checked = 0
        skipped = 0

        for policy in active_policies:
            rules = policy["rules"]
            policy_name = policy["name"]
            policy_id = policy["id"]

            if not rules["locally_enforceable"]:
                skipped += 1
                continue

            watched = [_normalize_file_path(f) for f in rules["watched_files"]]
            if normalized_path not in watched:
                if not rules["watched_files_complete"]:
                    notes.append(
                        f"Policy '{policy_name}' has watched_files the extractor "
                        f"could not fully parse; sandbox is authoritative on the "
                        f"next webhook event."
                    )
                skipped += 1
                continue

            checked += 1

            for pattern in rules["forbidden_patterns"]:
                kind = pattern["kind"]
                value = pattern["value"]
                new_counts = Counter(_matches(new_content, kind, value))
                prior_counts = (
                    Counter(_matches(prior_content, kind, value))
                    if prior_content is not None
                    else Counter()
                )
                introduced_diff = new_counts - prior_counts
                pre_existing_count += sum((new_counts & prior_counts).values())

                for matched_substring, count in introduced_diff.items():
                    for _ in range(count):
                        introduced.append(
                            {
                                "policy": policy_name,
                                "policy_id": policy_id,
                                "kind": kind,
                                "value": value,
                                "matched_substring": matched_substring,
                                "snippet": _snippet(new_content, matched_substring),
                            }
                        )

            if not rules["forbidden_patterns_complete"]:
                notes.append(
                    f"Policy '{policy_name}' has forbidden_patterns the extractor "
                    f"could not fully parse; sandbox is authoritative on the next "
                    f"webhook event."
                )

        return {
            "allowed": len(introduced) == 0,
            "introduced_violations": introduced,
            "pre_existing_violations_count": pre_existing_count,
            "checked": checked,
            "skipped": skipped,
            "notes": notes,
        }
