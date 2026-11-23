"""A stack's health: its projects counted, each with its health, worst
first, and when its map was last rebuilt. Shared by the stack page and the
API."""
from app.application.stack_health.project_health import ProjectHealth
from app.application.stack_health.stack_health import StackHealth

__all__ = ["ProjectHealth", "StackHealth"]
