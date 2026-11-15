"""A stack's health: its projects counted, each component with its
repository's health, worst first, and when its map was last rebuilt.
Shared by the stack page and the API."""
from app.application.stack_health.component_health import ComponentHealth
from app.application.stack_health.stack_health import StackHealth

__all__ = ["ComponentHealth", "StackHealth"]
