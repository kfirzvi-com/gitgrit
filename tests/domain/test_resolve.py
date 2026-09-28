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


class StrictResolveRefTests(SimpleTestCase):
    """A hand-written ``.gitgrit.yml`` target is an exact ref: never guessed."""

    def test_exact_refs_still_resolve(self):
        cases = {
            "org/web": WEB,
            "ORG/WEB/": WEB,
            "org/mono#apps/api-gateway": GATEWAY,
            "org/mono": MONO_ROOT,
        }
        for target, expected in cases.items():
            with self.subTest(target):
                self.assertEqual(resolve_ref(target, ROSTER, strict=True), expected)
        self.assertEqual(resolve_ref("#services/auth-service", ROSTER, this_repo="org/mono", strict=True), AUTH)

    def test_no_guessing(self):
        for target in (
            "other/web",  # same repo name, other owner
            "acme/mono#services/auth-service",  # other owner, same component path
            "org/web#notifications",  # missing folder
            "web",  # bare name
            "org/mono/apps/api-gateway",  # slash form
            "org/api-gateway",  # a unique component name as the last segment
        ):
            with self.subTest(target):
                self.assertIsNone(resolve_ref(target, ROSTER, strict=True))


class FileTopologyTests(SimpleTestCase):
    """A ``.gitgrit.yml`` map is kept as written: no LLM backstops."""

    def _file(self, **kw):
        return RepositoryTopology(components=(ComponentDecl("", "svc"),), source="file", **kw)

    def test_file_targets_are_exact(self):
        topo = self._file(internal=(InternalDependency("", "other/web"), InternalDependency("", "org/web")))
        out = resolve_topology(topo, ROSTER, this_repo="org/svc")
        self.assertEqual([r.target for r in out.internal], [WEB])
        self.assertEqual(out.unresolved, ("other/web",))

    def test_externals_and_infra_are_kept_as_written(self):
        topo = self._file(
            externals=(
                ExternalLink("", "AWS", OUTBOUND),
                ExternalLink("", "PostgreSQL", OUTBOUND),
                ExternalLink("", "Stripe", OUTBOUND),
                ExternalLink("", "Stripe API", OUTBOUND),
                ExternalLink("", "web", OUTBOUND),
                ExternalLink("", "Stripe", OUTBOUND),  # exact duplicate
            ),
            infrastructure=(InfrastructureResource("", "Redis", "other"), InfrastructureResource("", "mono", "other")),
        )
        out = resolve_topology(topo, ROSTER, this_repo="org/svc")
        self.assertEqual(
            [e.name for e in out.externals], ["AWS", "PostgreSQL", "Stripe", "Stripe API", "web"]
        )
        self.assertEqual([(i.name, i.kind) for i in out.infrastructure], [("Redis", "other"), ("mono", "other")])


class InfraKindTests(SimpleTestCase):
    def test_whole_words_only(self):
        from app.domain.architecture.resolve import infra_kind

        cases = {
            "Amazon RDS": "database",
            "S3 bucket": "storage",
            "aws-s3": "storage",
            "PostgreSQL 15": "database",
            "sqlite3": "database",
            "CockroachDB": "database",
            "Azure Blob Storage": "storage",
            "Rewards Platform": None,
            "Xero Sales3": None,
            "Redistribution API": None,
        }
        for name, kind in cases.items():
            with self.subTest(name):
                self.assertEqual(infra_kind(name), kind)
