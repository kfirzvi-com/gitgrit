"""Pure rules for an inferred repository topology: path normalisation, the
single-component→root rule, and the evidence gate."""
from django.test import SimpleTestCase

from app.domain.architecture.topology import (
    ComponentDecl,
    Evidence,
    RepositoryTopology,
    UngroundedTopology,
    check_evidence,
    clean_path,
    clean_technologies,
    normalise_components,
)

TREE = [
    "README.md",
    "package.json",
    "apps/api-gateway/package.json",
    "apps/api-gateway/src/index.ts",
    "services/auth-service/pyproject.toml",
    "packages/shared-lib/go.mod",
]


class NormaliseComponentsTests(SimpleTestCase):
    def test_no_components_means_the_root(self):
        out = normalise_components([], TREE, "mono")
        self.assertEqual(out, (ComponentDecl(path="", name="mono"),))

    def test_a_single_sub_component_is_forced_to_the_root(self):
        out = normalise_components([ComponentDecl("src", "src")], ["src/main.py"], "web")
        self.assertEqual([(c.path, c.name) for c in out], [("", "web")])

    def test_paths_are_cleaned_and_unknown_directories_dropped(self):
        out = normalise_components(
            [
                ComponentDecl("./apps/api-gateway/", "api-gateway", kind="service"),
                ComponentDecl("apps/does-not-exist", "ghost"),
                ComponentDecl("services/auth-service", "", kind="weird"),
            ],
            TREE,
            "mono",
        )
        self.assertEqual(
            [(c.path, c.name, c.kind) for c in out],
            [
                ("apps/api-gateway", "api-gateway", "service"),
                ("services/auth-service", "auth-service", "other"),  # name fallback, kind fallback
            ],
        )

    def test_duplicates_collapse_and_root_sorts_first(self):
        out = normalise_components(
            [
                ComponentDecl("packages/shared-lib", "shared-lib"),
                ComponentDecl("", "whatever the model said"),
                ComponentDecl("packages/shared-lib", "dup"),
            ],
            TREE,
            "mono",
        )
        self.assertEqual([(c.path, c.name) for c in out], [("", "mono"), ("packages/shared-lib", "shared-lib")])

    def test_component_count_is_capped(self):
        tree = [f"svc{i}/main.go" for i in range(40)]
        decls = [ComponentDecl(f"svc{i}", f"svc{i}") for i in range(40)]
        self.assertEqual(len(normalise_components(decls, tree, "mono", limit=25)), 25)

    def test_technologies_are_deduped_and_capped(self):
        self.assertEqual(clean_technologies(["Go", "go", " Next.js ", ""]), ("Go", "Next.js"))
        self.assertEqual(len(clean_technologies([f"t{i}" for i in range(30)])), 20)

    def test_clean_path(self):
        for raw in ("", ".", "./", "/", " / "):
            self.assertEqual(clean_path(raw), "")
        self.assertEqual(clean_path("./apps\\web/"), "apps/web")


class EvidenceGateTests(SimpleTestCase):
    def test_empty_tree_is_rejected_with_a_connection_hint(self):
        with self.assertRaises(UngroundedTopology) as ctx:
            check_evidence(Evidence(tree_size=0, files_read=()))
        self.assertIn("listing came back empty", str(ctx.exception))
        self.assertIn("connection", str(ctx.exception))

    def test_reading_nothing_is_rejected(self):
        with self.assertRaises(UngroundedTopology) as ctx:
            check_evidence(Evidence(tree_size=12, files_read=()))
        self.assertIn("without reading any repository file", str(ctx.exception))

    def test_grounded_evidence_passes(self):
        check_evidence(Evidence(tree_size=12, files_read=("package.json",)))


class TopologyCodecTests(SimpleTestCase):
    def test_dict_round_trip(self):
        topo = RepositoryTopology(
            components=(ComponentDecl("", "web", technologies=("Go",)),),
            evidence=Evidence(tree_size=3, files_read=("go.mod",)),
        )
        self.assertEqual(RepositoryTopology.from_dict(topo.to_dict()), topo)

    def test_from_dict_tolerates_missing_sections(self):
        topo = RepositoryTopology.from_dict({"components": [{"path": "", "name": "web"}]})
        self.assertEqual(topo.components[0].name, "web")
        self.assertEqual(topo.internal, ())
        self.assertIsNone(topo.evidence.tree_size)
