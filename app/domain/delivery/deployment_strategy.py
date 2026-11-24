from __future__ import annotations

from enum import StrEnum


class DeploymentStrategy(StrEnum):
    """How GitGrit tells that a project was deployed. Teams ship in different
    ways, so each project picks the signal that matches how it ships, or lets
    GitGrit detect one (``AUTO``)."""

    AUTO = "auto"
    ENVIRONMENTS = "environments"
    RELEASE_TAGS = "release_tags"
    DEPLOY_WORKFLOW = "deploy_workflow"
    DEPLOY_BRANCH = "deploy_branch"
    DEFAULT_BRANCH = "default_branch"
    REPORTED = "reported"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def description(self) -> str:
        return _DESCRIPTIONS[self]

    @classmethod
    def detection_order(cls) -> tuple[DeploymentStrategy, ...]:
        """The strategies ``AUTO`` tries, most precise first. The default
        branch comes last: every repository has one, so it always answers,
        but it only approximates a deployment."""
        return (cls.ENVIRONMENTS, cls.RELEASE_TAGS, cls.DEFAULT_BRANCH)

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(strategy.value, strategy.label) for strategy in cls]


_LABELS = {
    DeploymentStrategy.AUTO: "Detect automatically",
    DeploymentStrategy.ENVIRONMENTS: "Deployments to a production environment",
    DeploymentStrategy.RELEASE_TAGS: "Release tags",
    DeploymentStrategy.DEPLOY_WORKFLOW: "A deploy workflow",
    DeploymentStrategy.DEPLOY_BRANCH: "Pushes to a deploy branch",
    DeploymentStrategy.DEFAULT_BRANCH: "Pushes to the default branch",
    DeploymentStrategy.REPORTED: "Reported to GitGrit",
}

_DESCRIPTIONS = {
    DeploymentStrategy.AUTO: (
        "GitGrit looks for production deployments, then release tags, and falls "
        "back to pushes to the default branch."
    ),
    DeploymentStrategy.ENVIRONMENTS: (
        "Each successful deployment to a production environment, as the Git "
        "platform records it (a GitHub Actions job with an environment does)."
    ),
    DeploymentStrategy.RELEASE_TAGS: "Each tag that matches the release pattern, such as v1.4.0.",
    DeploymentStrategy.DEPLOY_WORKFLOW: "Each successful run of the named CI workflow on the default branch.",
    DeploymentStrategy.DEPLOY_BRANCH: "Each push to the deploy branch, such as production.",
    DeploymentStrategy.DEFAULT_BRANCH: (
        "Each push to the default branch. Exact for continuous deployment; "
        "an approximation otherwise."
    ),
    DeploymentStrategy.REPORTED: "Each deployment your pipeline reports to the GitGrit API.",
}
