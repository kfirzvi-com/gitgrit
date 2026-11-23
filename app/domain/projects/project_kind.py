"""What a project is, as the architecture diagram draws it."""
from django.db import models


class ProjectKind(models.TextChoices):
    SERVICE = "service", "Service / API"
    FRONTEND = "frontend", "Frontend / app"
    LIBRARY = "library", "Shared library"
    JOB = "job", "Job / pipeline"
    INFRA = "infra", "Infrastructure as code"
    OTHER = "other", "Other"

    @classmethod
    def parse(cls, value: str | None) -> "ProjectKind":
        """``value`` as a kind; anything unknown is ``OTHER``."""
        return cls(value) if value in cls.values else cls.OTHER
