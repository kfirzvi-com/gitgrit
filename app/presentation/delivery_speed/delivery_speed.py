from __future__ import annotations

from app.domain.delivery import DeliveryTotals, DoraBands
from app.presentation.delivery_speed.band import Band
from app.presentation.delivery_speed.band_meter import BandMeter
from app.presentation.delivery_speed.bar_tip import BarTip
from app.presentation.delivery_speed.info_tip import InfoTip
from app.presentation.speedometer import Speedometer

HOUR = 3600
DAY = 24 * HOUR
# DORA's bands, worst to best, in the colours the tier badges use.
DORA = (Band("Low", "bg-error"), Band("Medium", "bg-warning"), Band("High", "bg-info"), Band("Elite", "bg-success"))
# Deploys a week, worst to best: the speedometer's last band ends at 10.
DEPLOY_EDGES = (0.0, *DoraBands.DEPLOYS_A_WEEK, 10.0)
# Lead time in seconds, worst to best: the first band starts at 90 days.
LEAD_EDGES = (90 * DAY, *(limit.total_seconds() for limit in reversed(DoraBands.LEAD_TIME)), 0.0)
# How long open pull requests have been open (no DORA band): over a week is
# stale, over a day aging.
PULL_AGE = (Band("Stale", "bg-error"), Band("Aging", "bg-warning"), Band("Fresh", "bg-success"))
PULL_AGE_EDGES = (14 * DAY, 7 * DAY, DAY, 0.0)
# Weeks compared for the merge trend: the latest four against the four before.
TREND_WEEKS = 4

# What each part of the gauge means and how it is counted across the workspace.
TIPS = {
    "dora": InfoTip(
        "DORA metrics",
        "DORA (DevOps Research and Assessment) found four measures that predict how well teams ship: "
        "deployment frequency, lead time for changes, change failure rate and time to restore.",
        "Speed is the first two, shown here. Each is ranked in four bands, Low to Elite.",
        dora=True,
    ),
    "deploys": InfoTip(
        "Deploys a week",
        "Each project's deploys a week over the last 13 weeks. The gauge shows the median project: "
        "half deploy more often, half less.",
        "Elite: most days (3+ a week). High: weekly. Medium: monthly. Low: less often.",
        dora=True,
        reading_label="What good looks like",
    ),
    "lead": InfoTip(
        "Lead time for changes",
        "How long each change shipped in the last 13 weeks took to reach production, across every "
        "project (each from its own start, the commit by default). This is the median change.",
        "Elite: under a day. High: under a week. Medium: under a month. Low: longer.",
        dora=True,
        reading_label="What good looks like",
    ),
    "open": InfoTip(
        "Open pull requests",
        "Pull requests open now, added up across projects. The meter shows how long they have "
        "been open, the median one.",
        "Not a DORA metric. Fresh: under a day. Aging: under a week. Stale: longer.",
    ),
    "merged": InfoTip(
        "Merged a week",
        "Pull requests merged across every project, averaged over 13 weeks. The arrow compares the "
        "last 4 weeks with the 4 before.",
        "No right number: watch the trend.",
    ),
    "checks": InfoTip(
        "Commits checked",
        "Commits GitGrit checked against your standards this week, across every project, beside "
        "the busiest of the last 4 weeks.",
        "How actively standards run, not how good delivery is.",
    ),
}


class DeliverySpeed:
    """The dashboard cluster's delivery speed: a speedometer for the typical
    project's deploys a week, its arc coloured by DORA's bands so the needle
    shows how good it is, and beneath it lead time (DORA's bands), open pull
    requests (how long they have been open), merges a week (their trend) and
    commits checked (against the busiest of the last four weeks)."""

    def __init__(self, totals: DeliveryTotals, checks_this_week: int, checks_peak: int):
        self.totals = totals
        self.deploys = BandMeter(totals.typical_deploys_a_week if totals.deployments else None, DEPLOY_EDGES, DORA)
        self.speedometer = Speedometer(self.deploys.fraction * 100, 100)
        lead = totals.lead_time.total_seconds() if totals.lead_time is not None else None
        self.lead = BandMeter(lead, LEAD_EDGES, DORA)
        age = totals.open_age.total_seconds() if totals.open_age is not None else None
        self.pull_age = BandMeter(age, PULL_AGE_EDGES, PULL_AGE)
        self.checks_this_week = checks_this_week
        self.checks_peak = checks_peak

    @property
    def bar_tips(self) -> dict[str, BarTip]:
        """What each upright bar says on hover or focus."""
        from app.templatetags.time_tags import duration

        totals = self.totals
        lead = self.lead.band
        age = self.pull_age.band
        tier = self.deploy_tier
        counted = [f"{count} {band.label}" for band, count in totals.tiers if count]
        return {
            "deploys": BarTip(
                f"{totals.typical_deploys_a_week:.1f} deploys a week, typical project",
                f"{tier.label}: {tier.cadence.lower()}" if totals.deployments else "No deployments yet",
                "Projects: " + " · ".join(counted) if counted else "",
            ),
            "lead": BarTip(
                f"Lead time {duration(totals.lead_time)}",
                f"{lead.label}: {self.lead_tier.lead_time.lower()}" if lead else "No changes shipped yet",
                "Elite < 1 day · High < 1 week · Medium < 1 month",
            ),
            "merged": BarTip(
                f"{totals.merged_per_week:.1f} merged a week",
                f"{self.merged_trend_text} in the last 4 weeks against the 4 before" if self.merged_trend_text else "",
                f"Bar: the last 4 weeks at {self.merged_share}% of the busiest week",
            ),
            "open": BarTip(
                f"{totals.open_now} open pull request{'' if totals.open_now == 1 else 's'}",
                f"{age.label}: open {duration(totals.open_age)} (median)" if age else "None open",
                "Fresh < 1 day · Aging < 1 week · Stale beyond",
            ),
            "checks": BarTip(
                f"{self.checks_this_week} commit{'' if self.checks_this_week == 1 else 's'} checked this week",
                f"The busiest of the last 4 weeks had {self.checks_peak}",
                f"Bar: this week at {self.checks_share}% of that",
            ),
        }

    @property
    def lead_tier(self):
        return DoraBands.lead_time(self.totals.lead_time)

    @property
    def tips(self) -> dict[str, InfoTip]:
        return TIPS

    @property
    def bands(self) -> tuple[Band, ...]:
        """DORA's bands, best first, for a tip's legend."""
        return tuple(reversed(DORA))

    @property
    def deploy_tier(self):
        return DoraBands.deploy_rate(self.totals.typical_deploys_a_week)

    @property
    def zones(self) -> list[tuple[str, str, str]]:
        """Each DORA band's stretch of the speedometer's arc: (path, colour,
        what it means)."""
        width = 1 / len(DORA)
        low, medium, high = DoraBands.DEPLOYS_A_WEEK
        meanings = (
            f"Low: less than monthly, under {low:g} deploys a week",
            f"Medium: monthly, {low:g} to {medium:g} deploys a week",
            f"High: weekly, {medium:g} to {high:g} deploys a week",
            f"Elite: most days, {high:g} or more deploys a week",
        )
        return [
            (self.speedometer.zone_path(index * width, (index + 1) * width), band.css.replace("bg-", ""), meanings[index])
            for index, band in enumerate(DORA)
        ]

    @property
    def merged_trend(self) -> int | None:
        """Merges in the latest four weeks against the four before, in
        percent (None when the four before had none)."""
        merged = self.totals.merged
        latest, before = sum(merged[-TREND_WEEKS:]), sum(merged[-2 * TREND_WEEKS:-TREND_WEEKS])
        return round(100 * (latest - before) / before) if before else None

    @property
    def merged_trend_text(self) -> str:
        """The trend as an arrow and a percentage: "↑ 12%", "↓ 30%", "→ 0%"."""
        trend = self.merged_trend
        if trend is None:
            return ""
        arrow = "↑" if trend > 0 else "↓" if trend < 0 else "→"
        return f"{arrow} {abs(trend)}%"

    @property
    def merged_trend_arrow(self) -> str:
        trend = self.merged_trend
        if trend is None:
            return ""
        return "↑" if trend > 0 else "↓" if trend < 0 else "→"

    @property
    def merged_bars(self) -> list[int]:
        """The merges' weekly bars as heights in percent of the busiest."""
        most = max(self.totals.merged, default=0)
        return [round(100 * count / most) if most else 0 for count in self.totals.merged]

    @property
    def merged_share(self) -> int:
        """The last four weeks' merges a week against the busiest week, in
        percent: how full the merges bar stands."""
        merged = self.totals.merged
        most = max(merged, default=0)
        if not most:
            return 0
        return round(100 * sum(merged[-TREND_WEEKS:]) / TREND_WEEKS / most)

    @property
    def checks_share(self) -> int:
        return round(100 * self.checks_this_week / self.checks_peak) if self.checks_peak else 0
