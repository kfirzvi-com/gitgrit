"""The delivery domain: deployment strategies, production environments and
deployment frequency with its DORA tier."""
from datetime import date, datetime, time, timedelta, timezone

from django.test import SimpleTestCase

from app.domain.delivery import (
    LeadTime,
    LeadTimeStart,
    Shipment,
    ShippedCommit,
    DeliveryTotals,
    DeploymentEvent,
    DeploymentFrequency,
    DeploymentStrategy,
    DoraTier,
    PendingCommits,
    ProductionEnvironment,
    PullRequestFacts,
    PullRequestFlow,
    PullRequestState,
    RateLimit,
    RunningVersion,
    SyncPolicy,
)

TODAY = date(2026, 11, 16)  # a Monday


def deployed(day: date, sha: str, succeeded: bool = True, hour: int = 12) -> DeploymentEvent:
    return DeploymentEvent(
        strategy=DeploymentStrategy.ENVIRONMENTS,
        external_id=f"{sha}-{day}-{hour}",
        sha=sha,
        deployed_at=datetime.combine(day, time(hour), tzinfo=timezone.utc),
        succeeded=succeeded,
        environment="production",
    )


def every(days: int, weeks: int = 13) -> list[DeploymentEvent]:
    """One deployment every ``days`` days, newest today, each a new commit."""
    return [deployed(TODAY - timedelta(days=offset), f"c{offset}") for offset in range(0, weeks * 7, days)]


class DeploymentStrategyTests(SimpleTestCase):
    def test_detection_tries_precise_signals_before_the_default_branch(self):
        order = DeploymentStrategy.detection_order()

        self.assertEqual(order[-1], DeploymentStrategy.DEFAULT_BRANCH)
        self.assertNotIn(DeploymentStrategy.AUTO, order)

    def test_every_strategy_explains_itself(self):
        for strategy in DeploymentStrategy:
            self.assertTrue(strategy.label)
            self.assertTrue(strategy.description)


class ProductionEnvironmentTests(SimpleTestCase):
    def test_default_names_match_production_environments_by_word(self):
        production = ProductionEnvironment()

        for name in ("production", "Prod", "prod-eu", "us/production", "production_west"):
            self.assertTrue(production.matches(name), name)
        for name in ("staging", "preprod", "non-prod", "not_production", "dev", "productionish"):
            self.assertFalse(production.matches(name), name)

    def test_names_are_configurable_and_blank_means_the_default(self):
        self.assertTrue(ProductionEnvironment.from_text("live, prd").matches("eu-live"))
        self.assertEqual(ProductionEnvironment.from_text(" , ").names, ("production", "prod"))
        self.assertEqual(ProductionEnvironment.from_text("Live,live, PRD").as_text(), "live, prd")


class DeploymentEventTests(SimpleTestCase):
    def test_a_deployment_comes_from_a_concrete_strategy(self):
        with self.assertRaises(ValueError):
            DeploymentEvent(DeploymentStrategy.AUTO, "1", "abc", datetime.now(timezone.utc))

    def test_a_deployment_time_carries_its_timezone(self):
        with self.assertRaises(ValueError):
            DeploymentEvent(DeploymentStrategy.RELEASE_TAGS, "v1", "abc", datetime(2026, 11, 1))


class DeploymentFrequencyTests(SimpleTestCase):
    def test_the_window_is_thirteen_weeks_ending_today(self):
        frequency = DeploymentFrequency.of([], TODAY)

        self.assertEqual(len(frequency.weeks), 13)
        self.assertEqual(frequency.weeks[-1].starts + timedelta(days=6), TODAY)
        self.assertEqual(frequency.tier, DoraTier.NONE)

    def test_counts_changes_shipped_not_deploy_jobs(self):
        frequency = DeploymentFrequency.of(
            [
                deployed(TODAY, "a", hour=9),
                deployed(TODAY, "a", hour=10),  # redeploy of the same commit
                deployed(TODAY, "b", succeeded=False),  # failed: nothing shipped
                deployed(TODAY, "c"),
            ],
            TODAY,
        )

        self.assertEqual(frequency.total, 2)
        self.assertEqual(frequency.weeks[-1].deploy_days, 1)

    def test_a_commit_counts_on_its_first_successful_arrival(self):
        frequency = DeploymentFrequency.of(
            [deployed(TODAY, "a"), deployed(TODAY - timedelta(days=20), "a")], TODAY
        )

        self.assertEqual([week.deployments for week in frequency.weeks if week.deployments], [1])
        self.assertEqual(frequency.weeks[-3].deployments, 1)

    def test_deployments_outside_the_window_are_ignored(self):
        frequency = DeploymentFrequency.of(
            [deployed(TODAY - timedelta(weeks=13), "old"), deployed(TODAY + timedelta(days=1), "future")],
            TODAY,
        )

        self.assertEqual(frequency.total, 0)

    def test_days_are_counted_in_the_given_timezone(self):
        late_sunday_utc = DeploymentEvent(
            DeploymentStrategy.RELEASE_TAGS, "v1", "a", datetime(2026, 11, 15, 23, tzinfo=timezone.utc)
        )
        jerusalem = timezone(timedelta(hours=2))

        frequency = DeploymentFrequency.of([late_sunday_utc], TODAY + timedelta(days=6), tz=jerusalem)

        self.assertEqual(frequency.weeks[-1].deployments, 1)  # Monday the 16th there

    def test_tiers_follow_the_typical_week_and_month(self):
        self.assertEqual(DeploymentFrequency.of(every(1), TODAY).tier, DoraTier.ELITE)
        self.assertEqual(DeploymentFrequency.of(every(2), TODAY).tier, DoraTier.ELITE)  # 3-4 days a week
        self.assertEqual(DeploymentFrequency.of(every(3), TODAY).tier, DoraTier.HIGH)
        self.assertEqual(DeploymentFrequency.of(every(7), TODAY).tier, DoraTier.HIGH)
        # Every 14 days is the High/Medium boundary: it lands on whichever side
        # the window starts on, so the tests use clearer cadences around it.
        self.assertEqual(DeploymentFrequency.of(every(21), TODAY).tier, DoraTier.MEDIUM)
        self.assertEqual(DeploymentFrequency.of(every(28), TODAY).tier, DoraTier.MEDIUM)
        self.assertEqual(DeploymentFrequency.of(every(60), TODAY).tier, DoraTier.LOW)

    def test_one_busy_week_does_not_lift_a_quiet_quarter(self):
        burst = [deployed(TODAY - timedelta(days=day), f"b{day}") for day in range(7)]

        frequency = DeploymentFrequency.of(burst, TODAY)

        self.assertEqual(frequency.total, 7)
        self.assertEqual(frequency.tier, DoraTier.LOW)

    def test_per_week_is_the_average_over_the_window(self):
        self.assertAlmostEqual(DeploymentFrequency.of(every(7), TODAY).per_week, 1.0)


class SyncPolicyTests(SimpleTestCase):
    def test_a_sync_is_due_after_the_interval(self):
        policy = SyncPolicy(interval=timedelta(minutes=15))
        now = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)

        self.assertTrue(policy.is_due(None, now))
        self.assertFalse(policy.is_due(now - timedelta(minutes=14), now))
        self.assertTrue(policy.is_due(now - timedelta(minutes=15), now))

    def test_refreshing_by_hand_waits_out_the_cooldown(self):
        policy = SyncPolicy(cooldown=timedelta(minutes=5))
        synced = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)

        self.assertFalse(policy.may_refresh(synced, synced + timedelta(minutes=4)))
        self.assertTrue(policy.may_refresh(synced, synced + timedelta(minutes=5)))
        self.assertEqual(policy.next_refresh(synced), synced + timedelta(minutes=5))

    def test_the_interval_must_be_positive(self):
        with self.assertRaises(ValueError):
            SyncPolicy(interval=timedelta(0))


class RateLimitTests(SimpleTestCase):
    def test_low_below_a_tenth_of_the_allowance_until_it_resets(self):
        now = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
        low = RateLimit(limit=5000, remaining=499, resets_at=now + timedelta(minutes=10))

        self.assertTrue(low.is_low(now))
        self.assertFalse(low.is_low(now + timedelta(minutes=10)))
        self.assertFalse(RateLimit(limit=5000, remaining=500, resets_at=low.resets_at).is_low(now))


class RunningVersionTests(SimpleTestCase):
    def deploy(self, strategy, days_ago, ref="", succeeded=True, sha=None):
        return DeploymentEvent(
            strategy=strategy, external_id=f"{strategy}-{days_ago}", sha=sha or f"{days_ago:040d}",
            deployed_at=datetime(2026, 11, 20, tzinfo=timezone.utc) - timedelta(days=days_ago),
            succeeded=succeeded, ref=ref,
        )

    def test_the_newest_deployment_that_shipped_is_running(self):
        running = RunningVersion.latest([
            self.deploy(DeploymentStrategy.RELEASE_TAGS, 3, ref="v1.2.0"),
            self.deploy(DeploymentStrategy.RELEASE_TAGS, 1, ref="v1.3.0", succeeded=False),
            self.deploy(DeploymentStrategy.RELEASE_TAGS, 5, ref="v1.1.0"),
        ])

        self.assertEqual(running.label, "v1.2.0")
        self.assertTrue(running.tagged)

    def test_nothing_runs_before_a_deployment_ships(self):
        self.assertIsNone(RunningVersion.latest([]))

    def test_a_version_like_ref_names_it_else_the_short_commit(self):
        versioned = RunningVersion.latest([self.deploy(DeploymentStrategy.ENVIRONMENTS, 1, ref="2.4.1-rc.1")])
        branch = RunningVersion.latest([self.deploy(DeploymentStrategy.ENVIRONMENTS, 1, ref="main", sha="abcdef1234")])

        self.assertEqual(versioned.label, "2.4.1-rc.1")
        self.assertEqual(branch.label, "abcdef1")
        self.assertEqual(branch.version, "")


class PendingCommitsTests(SimpleTestCase):
    def test_waiting_commits_need_the_oldest_ones_time(self):
        with self.assertRaises(ValueError):
            PendingCommits(3)
        self.assertFalse(PendingCommits(0).any)


def pr(number, opened, merged=None, closed=None):
    """A pull request opened, merged or closed that many days before TODAY's noon."""
    noon = datetime.combine(TODAY, time(12), tzinfo=timezone.utc)

    def ago(days):
        return None if days is None else noon - timedelta(days=days)

    return PullRequestFacts(
        number=number, title=f"PR {number}", author="dev", url="", created_at=ago(opened),
        updated_at=ago(min(d for d in (opened, merged, closed) if d is not None)),
        merged_at=ago(merged), closed_at=ago(closed if closed is not None else merged),
    )


class PullRequestFlowTests(SimpleTestCase):
    def test_merges_count_in_the_week_they_landed(self):
        flow = PullRequestFlow.of([pr(1, opened=10, merged=2), pr(2, opened=9, merged=8), pr(3, opened=3)], TODAY)

        self.assertEqual(flow.weeks[-1].merged, 1)
        self.assertEqual(flow.weeks[-2].merged, 1)
        self.assertEqual(flow.merged, 2)
        self.assertAlmostEqual(flow.merged_per_week, 2 / 13)

    def test_open_at_each_weeks_end_counts_what_was_opened_and_not_yet_closed(self):
        flow = PullRequestFlow.of([pr(1, opened=20, merged=2), pr(2, opened=20, closed=10), pr(3, opened=3)], TODAY)

        self.assertEqual(flow.weeks[-3].open_at_end, 2)  # week ending 7 days before last week's end
        self.assertEqual(flow.weeks[-2].open_at_end, 1)
        self.assertEqual(flow.weeks[-1].open_at_end, 1)

    def test_open_now_and_the_oldest_one(self):
        flow = PullRequestFlow.of([pr(1, opened=30), pr(2, opened=3), pr(3, opened=40, closed=1)], TODAY)

        self.assertEqual(flow.open_now, 2)
        self.assertEqual(flow.oldest_open_since, datetime.combine(TODAY, time(12), tzinfo=timezone.utc) - timedelta(days=30))

    def test_a_pull_request_closed_unmerged_is_no_merge(self):
        closed = pr(1, opened=5, closed=1)

        self.assertIs(closed.state, PullRequestState.CLOSED)
        self.assertEqual(PullRequestFlow.of([closed], TODAY).merged, 0)


class DeliveryTotalsTests(SimpleTestCase):
    def frequency(self, every_days):
        return DeploymentFrequency.of(every(every_days), TODAY)

    def test_sums_each_week_over_the_projects_and_counts_their_tiers(self):
        daily, weekly = self.frequency(1), self.frequency(7)
        flows = [PullRequestFlow.of([pr(1, opened=3)], TODAY), PullRequestFlow.of([pr(2, opened=9, merged=1)], TODAY)]

        totals = DeliveryTotals.of([daily, weekly], flows)

        self.assertEqual(totals.deployments[-1], daily.weeks[-1].deployments + weekly.weeks[-1].deployments)
        self.assertEqual(totals.merged[-1], 1)
        self.assertEqual(totals.open_now, 1)
        self.assertEqual(dict(totals.tiers)[DoraTier.ELITE], 1)
        self.assertEqual(dict(totals.tiers)[DoraTier.HIGH], 1)
        self.assertEqual(len(totals.starts), 13)

    def test_no_projects_add_up_to_nothing(self):
        totals = DeliveryTotals.of([], [])

        self.assertEqual(totals.deployments, ())
        self.assertEqual(totals.deployments_per_week, 0.0)


class PullRequestOpenTimeTests(SimpleTestCase):
    def test_time_to_merge_is_the_median_from_opening_to_merge(self):
        flow = PullRequestFlow.of([pr(1, opened=10, merged=9), pr(2, opened=10, merged=7), pr(3, opened=10, merged=4)], TODAY)

        self.assertEqual(flow.time_to_merge, timedelta(days=3))
        self.assertEqual(flow.weeks[-1].time_to_merge, timedelta(days=6))  # only #3 merged this week
        self.assertEqual(flow.weeks[-2].time_to_merge, timedelta(days=2))  # #1 and #2: 1 and 3 days
        self.assertIsNone(flow.weeks[0].time_to_merge)

    def test_open_ones_are_aged_to_now(self):
        noon = datetime.combine(TODAY, time(12), tzinfo=timezone.utc)

        flow = PullRequestFlow.of([pr(1, opened=2), pr(2, opened=6), pr(3, opened=30, merged=1)], TODAY, now=noon)

        self.assertEqual(flow.open_age, timedelta(days=4))

    def test_nothing_merged_or_open_has_no_times(self):
        flow = PullRequestFlow.of([], TODAY)

        self.assertIsNone(flow.time_to_merge)
        self.assertIsNone(flow.open_age)


NOON = datetime.combine(TODAY, time(12), tzinfo=timezone.utc)


def commit(sha, hours_ago, parent=""):
    return ShippedCommit(sha=sha, authored_at=NOON - timedelta(hours=hours_ago), first_parent_sha=parent)


def merged_pr(number, merge_sha, opened_hours_ago, merged_hours_ago, ready_hours_ago=None):
    return PullRequestFacts(
        number=number, title="", author="", url="",
        created_at=NOON - timedelta(hours=opened_hours_ago), updated_at=NOON,
        merged_at=NOON - timedelta(hours=merged_hours_ago), closed_at=NOON - timedelta(hours=merged_hours_ago),
        merge_commit_sha=merge_sha,
        ready_at=NOON - timedelta(hours=ready_hours_ago) if ready_hours_ago is not None else None,
    )


class LeadTimeTests(SimpleTestCase):
    def shipment(self):
        """Deployed at noon today: a merge commit M (PR #7, its inner commits
        a and b off the line) on top of a direct push D."""
        return Shipment(head_sha="M", deployed_at=NOON, commits=(
            commit("M", 2, parent="D"), commit("b", 30, parent="a"), commit("a", 50, parent="D0"),
            commit("D", 10, parent="X"),
        ))

    def test_from_commit_every_commit_counts_from_when_it_was_written(self):
        lead = LeadTime.of([self.shipment()], [merged_pr(7, "M", 40, 2)], TODAY)

        self.assertEqual(sorted(c.length for c in lead.changes), [timedelta(hours=h) for h in (2, 10, 30, 50)])
        self.assertEqual(lead.median, timedelta(hours=20))
        self.assertEqual(lead.tier, DoraTier.ELITE)

    def test_from_ready_a_pull_request_counts_once_and_a_direct_push_from_its_commit(self):
        lead = LeadTime.of([self.shipment()], [merged_pr(7, "M", 40, 2, ready_hours_ago=36)], TODAY, LeadTimeStart.READY)

        self.assertEqual({c.pull_request: c.length for c in lead.changes},
                         {None: timedelta(hours=10), 7: timedelta(hours=36)})
        self.assertEqual(lead.review, timedelta(hours=34))
        self.assertEqual(lead.waiting, timedelta(hours=2))

    def test_a_pull_request_never_a_draft_was_ready_when_opened(self):
        lead = LeadTime.of([self.shipment()], [merged_pr(7, "M", 40, 2)], TODAY, LeadTimeStart.READY)

        self.assertIn(timedelta(hours=40), [c.length for c in lead.changes])

    def test_from_merge_only_the_wait_for_production_counts_for_a_pull_request(self):
        lead = LeadTime.of([self.shipment()], [merged_pr(7, "M", 40, 2)], TODAY, LeadTimeStart.MERGE)

        self.assertEqual(sorted(c.length for c in lead.changes), [timedelta(hours=2), timedelta(hours=10)])

    def test_tiers_follow_doras_bands(self):
        def tier(hours):
            shipment = Shipment("c", NOON, (commit("c", hours),))
            return LeadTime.of([shipment], [], TODAY).tier

        self.assertEqual(tier(23), DoraTier.ELITE)
        self.assertEqual(tier(24 * 6), DoraTier.HIGH)
        self.assertEqual(tier(24 * 20), DoraTier.MEDIUM)
        self.assertEqual(tier(24 * 40), DoraTier.LOW)
        self.assertEqual(LeadTime.of([], [], TODAY).tier, DoraTier.NONE)

    def test_only_shipments_in_the_window_count_by_the_week_they_shipped(self):
        old = Shipment("o", NOON - timedelta(weeks=14), (commit("o", 24 * 7 * 14 + 1),))
        last_week = Shipment("w", NOON - timedelta(days=7), (commit("w", 24 * 7 + 5),))

        lead = LeadTime.of([old, last_week, self.shipment()], [], TODAY)

        self.assertEqual(len(lead.changes), 5)
        self.assertEqual(lead.weeks[-2].changes, 1)
        self.assertEqual(lead.weeks[-2].median, timedelta(hours=5))
        self.assertEqual(lead.weeks[-1].changes, 4)


class ReadyForReviewTests(SimpleTestCase):
    def facts(self, draft=False, ready_at=None):
        return PullRequestFacts(number=1, title="", author="", url="", created_at=NOON - timedelta(days=2),
                                updated_at=NOON, draft=draft, ready_at=ready_at)

    def test_ready_when_opened_unless_seen_leaving_draft(self):
        self.assertEqual(self.facts().ready_since(None, None), NOON - timedelta(days=2))
        self.assertEqual(self.facts().ready_since(True, None), NOON)
        self.assertIsNone(self.facts(draft=True).ready_since(None, None))

    def test_a_known_time_is_kept(self):
        known = NOON - timedelta(days=1)

        self.assertEqual(self.facts().ready_since(False, known), known)
        self.assertEqual(self.facts(ready_at=known).ready_since(None, None), known)


class DoraBandsTests(SimpleTestCase):
    def test_a_weekly_deploy_rate_falls_in_doras_bands(self):
        from app.domain.delivery import DoraBands

        self.assertEqual(DoraBands.deploy_rate(0), DoraTier.NONE)
        self.assertEqual(DoraBands.deploy_rate(0.1), DoraTier.LOW)
        self.assertEqual(DoraBands.deploy_rate(0.5), DoraTier.MEDIUM)
        self.assertEqual(DoraBands.deploy_rate(2), DoraTier.HIGH)
        self.assertEqual(DoraBands.deploy_rate(3), DoraTier.ELITE)
