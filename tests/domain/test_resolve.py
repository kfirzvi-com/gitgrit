"""Mapping model-returned names onto the workspace roster, and the
classification backstops applied to a whole topology."""
from django.test import SimpleTestCase

from app.domain.architecture.resolve import RosterEntry, resolve_ref, resolve_topology
from app.domain.architecture.topology import (
    INBOUND,
    OUTBOUND,
    ComponentDecl,
    ExternalLink,
    InfrastructureResource,
    InternalDependency,
    RepositoryTopology,
)

WEB = RosterEntry("org/web", "", "web", component_id="web")
MONO_ROOT = RosterEntry("org/mono", "", "mono", component_id="mono")
GATEWAY = RosterEntry("org/mono", "apps/api-gateway", "api-gateway", component_id="gw")
AUTH = RosterEntry("org/mono", "services/auth-service", "auth-service", component_id="auth")
ROSTER = (WEB, MONO_ROOT, GATEWAY, AUTH)


class ResolveRefTests(SimpleTestCase):
    def test_every_ref_form(self):
        cases = {
            "org/web": WEB,  # root by full_path
            "web": WEB,  # root by name
            "ORG/WEB/": WEB,  # case and trailing slash
            "org/mono#apps/api-gateway": GATEWAY,  # canonical ref
            "org/mono/apps/api-gateway": GATEWAY,  # slash form
            "auth-service": AUTH,  # unique component name
            "org/mono": MONO_ROOT,  # bare monorepo → its root
            "org/nope": None,
            "": None,
        }
        for target, expected in cases.items():
            with self.subTest(target=target):
                self.assertEqual(resolve_ref(target, ROSTER), expected)

    def test_sibling_shorthand_within_this_repo(self):
        self.assertEqual(resolve_ref("#services/auth-service", ROSTER, this_repo="org/mono"), AUTH)
        self.assertEqual(resolve_ref("services/auth-service", ROSTER, this_repo="org/mono"), AUTH)
        self.assertIsNone(resolve_ref("#services/auth-service", ROSTER, this_repo="org/web"))

    def test_ambiguous_name_resolves_to_nothing(self):
        roster = ROSTER + (RosterEntry("org/other", "svc/auth-service", "auth-service"),)
        self.assertIsNone(resolve_ref("auth-service", roster))

    def test_bare_repo_with_no_root_but_one_component(self):
        roster = (GATEWAY,)
        self.assertEqual(resolve_ref("org/mono", roster), GATEWAY)


class ResolveTopologyTests(SimpleTestCase):
    def _topology(self, **kw):
        base = dict(
            components=(ComponentDecl("", "svc"),),
            internal=(),
            externals=(),
            infrastructure=(),
        )
        base.update(kw)
        return RepositoryTopology(**base)

    def test_internal_targets_resolve_and_dedupe(self):
        topo = self._topology(
            internal=(
                InternalDependency("", "org/web", "REST"),
                InternalDependency("", "web", "again"),  # same target → deduped
                InternalDependency("", "org/nope"),
                InternalDependency("", "org/svc"),  # ourselves → dropped
            )
        )
        roster = ROSTER + (RosterEntry("org/svc", "", "svc"),)
        out = resolve_topology(topo, roster, this_repo="org/svc")
        self.assertEqual([(r.target, r.label) for r in out.internal], [(WEB, "REST")])
        self.assertEqual(out.unresolved, ("org/nope",))

    def test_sibling_edges_in_a_monorepo(self):
        topo = self._topology(
            components=(ComponentDecl("apps/api-gateway", "api-gateway"), ComponentDecl("services/auth-service", "auth-service")),
            internal=(InternalDependency("apps/api-gateway", "#services/auth-service", "OAuth"),),
        )
        roster = (WEB, RosterEntry("org/mono", "apps/api-gateway", "api-gateway"), RosterEntry("org/mono", "services/auth-service", "auth-service"))
        out = resolve_topology(topo, roster, this_repo="org/mono")
        self.assertEqual(out.internal[0].target.path, "services/auth-service")
        self.assertIsNone(out.internal[0].target.component_id)  # sibling, not yet persisted

    def test_external_backstops(self):
        topo = self._topology(
            externals=(
                ExternalLink("", "Stripe", OUTBOUND, url="https://stripe.com"),
                ExternalLink("", "Stripe API", OUTBOUND),  # same service → deduped
                ExternalLink("", "PostgreSQL", OUTBOUND),  # datastore → infrastructure
                ExternalLink("", "AWS", OUTBOUND),  # bare cloud → dropped
                ExternalLink("", "web", OUTBOUND),  # a workspace component → dropped
                ExternalLink("", "Partner API", INBOUND),
            ),
            infrastructure=(InfrastructureResource("", "Redis", "cache"), InfrastructureResource("", "redis", "cache")),
        )
        out = resolve_topology(topo, ROSTER, this_repo="org/svc")
        self.assertEqual([(e.name, e.direction) for e in out.externals], [("Stripe", OUTBOUND), ("Partner API", INBOUND)])
        self.assertEqual(sorted((i.name, i.kind) for i in out.infrastructure), [("PostgreSQL", "database"), ("Redis", "cache")])

    def test_unknown_infra_kind_falls_back_to_name_lookup_then_other(self):
        topo = self._topology(
            infrastructure=(InfrastructureResource("", "Kafka", "stream"), InfrastructureResource("", "Widget", "stream"))
        )
        out = resolve_topology(topo, ROSTER, this_repo="org/svc")
        self.assertEqual({i.name: i.kind for i in out.infrastructure}, {"Kafka": "queue", "Widget": "other"})

    def test_entries_for_unknown_source_paths_are_ignored(self):
        topo = self._topology(internal=(InternalDependency("nope", "org/web"),))
        out = resolve_topology(topo, ROSTER, this_repo="org/svc")
        self.assertEqual(out.internal, ())
