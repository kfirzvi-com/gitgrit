from __future__ import annotations

from django import forms

from app.domain.delivery import DeploymentStrategy
from app.models import DeliverySettings


class DeliverySettingsForm(forms.ModelForm):
    """How a project's deployments are counted: the strategy and the one or
    two settings each strategy reads."""

    # Which settings each strategy reads, so the page only shows those.
    FIELDS_FOR = {
        "production_environments": (DeploymentStrategy.AUTO, DeploymentStrategy.ENVIRONMENTS),
        "release_tag_pattern": (DeploymentStrategy.AUTO, DeploymentStrategy.RELEASE_TAGS),
        "deploy_workflow": (DeploymentStrategy.DEPLOY_WORKFLOW,),
        "deploy_branch": (DeploymentStrategy.DEPLOY_BRANCH,),
    }

    class Meta:
        model = DeliverySettings
        fields = ["strategy", "production_environments", "release_tag_pattern", "deploy_workflow", "deploy_branch"]
        labels = {
            "strategy": "Count a deployment as",
            "production_environments": "Production environments",
            "release_tag_pattern": "Release tag pattern",
            "deploy_workflow": "Deploy workflow file",
            "deploy_branch": "Deploy branch",
        }
        help_texts = {
            "production_environments": "Comma-separated names; an environment counts when a word in its name matches. Blank: production, prod.",
            "release_tag_pattern": "Shell-style pattern, such as v* or release-*.",
            "deploy_workflow": "The workflow's file name, such as deploy.yml.",
            "deploy_branch": "Every push to this branch is a deployment.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "select select-sm w-full" if name == "strategy" else "input input-sm w-full"
            if name in self.FIELDS_FOR:
                field.widget.attrs["data-show-for"] = " ".join(s.value for s in self.FIELDS_FOR[name])
        self.fields["strategy"].widget.attrs["data-strategy-select"] = ""

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("strategy") == DeploymentStrategy.DEPLOY_WORKFLOW and not cleaned.get("deploy_workflow", "").strip():
            self.add_error("deploy_workflow", "Name the workflow file that deploys.")
        if cleaned.get("strategy") == DeploymentStrategy.DEPLOY_BRANCH and not cleaned.get("deploy_branch", "").strip():
            self.add_error("deploy_branch", "Name the branch that deploys.")
        return cleaned
