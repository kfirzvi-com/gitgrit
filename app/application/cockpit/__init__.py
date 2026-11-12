"""The dashboard's cockpit: instruments that count projects, warning lights
that turn on only when a standard needs action, the projects that need you,
and how the workspace's health moved."""
from app.application.cockpit.attention_row import AttentionRow
from app.application.cockpit.cockpit import Cockpit
from app.application.cockpit.health_trend import HealthTrend
from app.application.cockpit.trend_point import TrendPoint
from app.application.cockpit.warning_light import WarningLight

__all__ = ["AttentionRow", "Cockpit", "HealthTrend", "TrendPoint", "WarningLight"]
