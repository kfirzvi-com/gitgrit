"""Mapping model-returned names onto the workspace roster (its projects), and
the classification backstops applied to a whole topology."""
from django.test import SimpleTestCase

from app.domain.architecture.resolve import RosterEntry, resolve_ref, resolve_topology
from app.domain.architecture.topology import (
    INBOUND,
    OUTBOUND,
    ExternalLink,
    InfrastructureResource,
    InternalDependency,
    ProjectTopology,
)

WEB = RosterEntry("org/web", "", "web", project_id="web")
MONO_ROOT = RosterEntry("org/mono", "", "mono", project_id="mono")
GATEWAY = RosterEntry("org/mono", "apps/api-gateway", "api-gateway", project_id="gw")
AUTH = RosterEntry("org/mono", "services/auth-service", "auth-service", project_id="auth")
ROSTER = (WEB, MONO_ROOT, GATEWAY, AUTH)


class ResolveRefTests(SimpleTestCase):
    def test_every_ref_form(self):
        cases = {
            "org/web": WEB,  # whole-repository project by full_path
            "web": WEB,  # by name
            "ORG/WEB/": WEB,  # case and trailing slash
            "org/mono#apps/api-gateway": GATEWAY,  # canonical ref
            "org/mono/apps/api-gateway": GATEWAY,  # slash form
            "auth-service": AUTH,  # unique project name
            "org/mono": MONO_ROOT,  # bare monorepo → its whole-repository project
            "org/nope": None,
            "": None,
        }
        for target, expected in cases.items():
            with self.subTest(target=target):
                self.assertEqual(resolve_ref(target, ROSTER), expected)

    def test_same_repository_shorthand(self):
        self.assertEqual(resolve_ref("#services/auth-service", ROSTER, this_repo="org/mono"), AUTH)
        self.assertEqual(resolve_ref("services/auth-service", ROSTER, this_repo="org/mono"), AUTH)
        self.assertIsNone(resolve_ref("#services/auth-service", ROSTER, this_repo="org/web"))

    def test_ambiguous_name_resolves_to_nothing(self):
        roster = ROSTER + (RosterEntry("org/other", "svc/auth-service", "auth-service"),)
        self.assertIsNone(resolve_ref("auth-service", roster))

    def test_bare_repo_with_no_whole_repository_project_but_one_project(self):
        self.assertEqual(resolve_ref("org/mono", (GATEWAY,)), GATEWAY)


class ResolveTopologyTests(SimpleTestCase):
    def test_internal_targets_resolve_and_dedupe(self):
        topo = ProjectTopology(
            internal=(
                InternalDependency("org/web", "REST"),
                InternalDependency("web", "again"),  # same target → deduped
                InternalDependency("org/nope"),
                InternalDependency("org/svc"),  # ourselves → dropped
            )
        )
        roster = ROSTER + (RosterEntry("org/svc", "", "svc"),)
        out = resolve_topology(topo, roster, this_repo="org/svc")
        self.assertEqual([(r.target, r.label) for r in out.internal], [(WEB, "REST")])
        self.assertEqual(out.unresolved, ("org/nope",))

    def test_edges_between_projects_of_one_monorepo(self):
        topo = ProjectTopology(internal=(InternalDependency("#services/auth-service", "OAuth"),))
        out = resolve_topology(topo, ROSTER, this_repo="org/mono", this_path="apps/api-gateway")
        self.assertEqual(out.internal[0].target, AUTH)

    def test_an_edge_to_itself_is_dropped(self):
        topo = ProjectTopology(internal=(InternalDependency("#apps/api-gateway"),))
        out = resolve_topology(topo, ROSTER, this_repo="org/mono", this_path="apps/api-gateway")
        self.assertEqual(out.internal, ())

    def test_external_backstops(self):
        topo = ProjectTopology(
            externals=(
                ExternalLink("Stripe", OUTBOUND, url="https://stripe.com"),
                ExternalLink("Stripe API", OUTBOUND),  # same service → deduped
                ExternalLink("PostgreSQL", OUTBOUND),  # datastore → infrastructure
                ExternalLink("AWS", OUTBOUND),  # bare cloud → dropped
                ExternalLink("web", OUTBOUND),  # a workspace project → dropped
                ExternalLink("Partner API", INBOUND),
            ),
            infrastructure=(InfrastructureResource("Redis", "cache"), InfrastructureResource("redis", "cache")),
        )
        out = resolve_topology(topo, ROSTER, this_repo="org/svc")
        self.assertEqual([(e.name, e.direction) for e in out.externals], [("Stripe", OUTBOUND), ("Partner API", INBOUND)])
        self.assertEqual(sorted((i.name, i.kind) for i in out.infrastructure), [("PostgreSQL", "database"), ("Redis", "cache")])

    def test_unknown_infra_kind_falls_back_to_name_lookup_then_other(self):
        topo = ProjectTopology(
            infrastructure=(InfrastructureResource("Kafka", "stream"), InfrastructureResource("Widget", "stream"))
        )
        out = resolve_topology(topo, ROSTER, this_repo="org/svc")
        self.assertEqual({i.name: i.kind for i in out.infrastructure}, {"Kafka": "queue", "Widget": "other"})
