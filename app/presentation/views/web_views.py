import json
from collections import defaultdict

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import TemplateView

from app.domain.models import (
    Membership,
    PlatformConnection,
    Policy,
    PolicyExecution,
    PolicyLabel,
    Project,
)


class HomeView(TemplateView):
    template_name = "pages/home.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "pages/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tenant = self.request.tenant
        tab = self.request.GET.get("tab", "overview")
        context["tab"] = tab

        if tenant:
            membership = Membership.objects.filter(
                user=self.request.user, tenant=tenant
            ).first()
            context["is_admin"] = membership and membership.role in (
                Membership.Role.OWNER,
                Membership.Role.ADMIN,
            )
            context["has_connections"] = PlatformConnection.objects.filter(
                tenant=tenant
            ).exists()
            context["project_count"] = Project.objects.filter(tenant=tenant).count()
            context["policy_count"] = Policy.objects.filter(
                tenant=tenant, enabled=True
            ).count()

            # Recent executions across all tenant projects
            tenant_projects = Project.objects.filter(tenant=tenant)
            recent_executions = PolicyExecution.objects.filter(
                project__in=tenant_projects
            ).select_related("policy", "project")[:10]
            context["recent_executions"] = recent_executions

            # Compliance score: average of latest-per-policy scores across all projects
            all_executions = PolicyExecution.objects.filter(
                project__in=tenant_projects
            ).select_related("policy").order_by("-created_at")[:200]
            seen = {}
            for ex in all_executions:
                key = (ex.project_id, ex.policy_id or ex.policy_name)
                if key not in seen:
                    seen[key] = ex
            latest = list(seen.values())
            if latest:
                context["compliance_score"] = round(
                    sum(ex.score for ex in latest) / len(latest)
                )
            else:
                context["compliance_score"] = None

            # Analytics data (for analytics tab)
            if tab == "analytics":
                demo = self.request.GET.get("demo") == "1"
                context["demo_mode"] = demo
                if demo:
                    context["analytics_data"] = json.dumps(_get_demo_data())
                else:
                    context["analytics_data"] = json.dumps(
                        _get_analytics_data(tenant)
                    )
        else:
            context["project_count"] = 0
            context["policy_count"] = 0
            context["recent_executions"] = []
            context["compliance_score"] = None
            if tab == "analytics":
                context["demo_mode"] = self.request.GET.get("demo") == "1"
                context["analytics_data"] = json.dumps(
                    _get_demo_data() if context["demo_mode"] else _get_empty_data()
                )
        return context


def _get_analytics_data(tenant):
    projects = list(
        Project.objects.filter(tenant=tenant).values("pk", "name", "languages")
    )
    policies = list(
        Policy.objects.filter(tenant=tenant, enabled=True).prefetch_related("labels")
    )
    labels = list(PolicyLabel.objects.filter(tenant=tenant).values("pk", "name"))

    thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
    executions = list(
        PolicyExecution.objects.filter(
            project__tenant=tenant,
            created_at__gte=thirty_days_ago,
        )
        .select_related("policy", "project")
        .order_by("created_at")
    )

    # Compliance trend by day
    daily_scores = defaultdict(list)
    for ex in executions:
        day = ex.created_at.strftime("%Y-%m-%d")
        daily_scores[day].append(ex.score)

    trend_labels = sorted(daily_scores.keys())
    trend_scores = [
        round(sum(daily_scores[d]) / len(daily_scores[d])) for d in trend_labels
    ]

    # Scores by label
    label_scores = {}
    for policy in policies:
        policy_execs = [e for e in executions if e.policy_id == policy.pk]
        if not policy_execs:
            continue
        avg = round(sum(e.score for e in policy_execs) / len(policy_execs))
        for label in policy.labels.all():
            if label.name not in label_scores:
                label_scores[label.name] = []
            label_scores[label.name].append(avg)

    label_names = list(label_scores.keys())
    label_avgs = [
        round(sum(scores) / len(scores)) for scores in label_scores.values()
    ]

    # Per-project scores
    project_scores = []
    for proj in projects:
        proj_execs = [e for e in executions if str(e.project_id) == str(proj["pk"])]
        if proj_execs:
            seen = {}
            for ex in sorted(proj_execs, key=lambda e: e.created_at, reverse=True):
                key = ex.policy_id or ex.policy_name
                if key not in seen:
                    seen[key] = ex
            avg = round(sum(e.score for e in seen.values()) / len(seen))
        else:
            avg = None
        project_scores.append({
            "name": proj["name"],
            "score": avg,
            "languages": proj["languages"] or [],
        })

    # Top failing policies
    policy_fail_counts = defaultdict(int)
    policy_total_counts = defaultdict(int)
    for ex in executions:
        name = ex.policy_name
        policy_total_counts[name] += 1
        if ex.status in ("failed", "error"):
            policy_fail_counts[name] += 1

    top_failing = sorted(
        [
            {
                "name": name,
                "failures": policy_fail_counts[name],
                "total": policy_total_counts[name],
                "rate": round(
                    policy_fail_counts[name] / policy_total_counts[name] * 100
                ),
            }
            for name in policy_total_counts
            if policy_fail_counts.get(name, 0) > 0
        ],
        key=lambda x: x["failures"],
        reverse=True,
    )[:5]

    return {
        "trend": {"labels": trend_labels, "scores": trend_scores},
        "labels": {"names": label_names, "scores": label_avgs},
        "projects": project_scores,
        "top_failing": top_failing,
        "summary": {
            "projects": len(projects),
            "policies": len(policies),
            "executions": len(executions),
            "labels": len(labels),
        },
    }


def _get_demo_data():
    import random

    random.seed(42)
    days = [
        (timezone.now() - timezone.timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(29, -1, -1)
    ]
    base = 62
    trend_scores = []
    for _ in range(30):
        base = min(98, max(40, base + random.randint(-3, 5)))
        trend_scores.append(base)

    return {
        "trend": {"labels": days, "scores": trend_scores},
        "labels": {
            "names": ["security", "quality", "documentation", "best-practices", "ci-cd"],
            "scores": [88, 72, 95, 64, 81],
        },
        "projects": [
            {"name": "api-gateway", "score": 92, "languages": ["Go", "Dockerfile"]},
            {"name": "web-frontend", "score": 85, "languages": ["TypeScript", "CSS"]},
            {"name": "auth-service", "score": 78, "languages": ["Python", "Dockerfile"]},
            {"name": "data-pipeline", "score": 61, "languages": ["Python", "SQL"]},
            {"name": "mobile-app", "score": 45, "languages": ["Kotlin", "Swift"]},
            {"name": "infra-terraform", "score": 94, "languages": ["HCL", "Shell"]},
            {"name": "shared-libs", "score": 88, "languages": ["TypeScript"]},
            {"name": "ml-platform", "score": 53, "languages": ["Python", "YAML"]},
            {"name": "notification-svc", "score": 71, "languages": ["Java"]},
            {"name": "admin-dashboard", "score": 96, "languages": ["TypeScript", "CSS"]},
        ],
        "top_failing": [
            {"name": "Branch Protection", "failures": 14, "total": 40, "rate": 35},
            {"name": "Required CI Config", "failures": 11, "total": 40, "rate": 28},
            {"name": "CODEOWNERS File", "failures": 9, "total": 40, "rate": 23},
            {"name": "No Secrets in Code", "failures": 5, "total": 40, "rate": 13},
            {"name": "License File", "failures": 3, "total": 40, "rate": 8},
        ],
        "summary": {
            "projects": 10,
            "policies": 12,
            "executions": 847,
            "labels": 5,
        },
    }


def _get_empty_data():
    return {
        "trend": {"labels": [], "scores": []},
        "labels": {"names": [], "scores": []},
        "projects": [],
        "top_failing": [],
        "summary": {"projects": 0, "policies": 0, "executions": 0, "labels": 0},
    }
