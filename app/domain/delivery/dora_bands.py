from __future__ import annotations

from datetime import timedelta

from app.domain.delivery.dora_tier import DoraTier


class DoraBands:
    """DORA's performance bands as plain thresholds, for placing one number
    (a project's deploys a week, a median lead time) in a tier.

    * Deploys a week: Elite on 3 or more (deploying most days), High from
      1 (weekly), Medium from 0.25 (monthly), Low below that. A project's own
      deployment frequency tier reads its weeks, not this average
      (``DeploymentFrequency.tier``); this is for a single rate.
    * Lead time: Elite under a day, High under a week, Medium under a
      month, Low longer.
    """

    DEPLOYS_A_WEEK = (0.25, 1.0, 3.0)
    LEAD_TIME = (timedelta(days=1), timedelta(weeks=1), timedelta(days=30))

    @classmethod
    def deploy_rate(cls, per_week: float) -> DoraTier:
        low, medium, high = cls.DEPLOYS_A_WEEK
        if per_week <= 0:
            return DoraTier.NONE
        if per_week >= high:
            return DoraTier.ELITE
        if per_week >= medium:
            return DoraTier.HIGH
        if per_week >= low:
            return DoraTier.MEDIUM
        return DoraTier.LOW

    @classmethod
    def lead_time(cls, length: timedelta | None) -> DoraTier:
        if length is None:
            return DoraTier.NONE
        day, week, month = cls.LEAD_TIME
        if length < day:
            return DoraTier.ELITE
        if length < week:
            return DoraTier.HIGH
        if length < month:
            return DoraTier.MEDIUM
        return DoraTier.LOW
