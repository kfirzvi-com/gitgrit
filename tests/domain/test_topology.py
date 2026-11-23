"""Pure rules for an inferred project topology: which discovered units are
worth suggesting as projects, path normalisation, a project's slice of a
whole-repository description, and the evidence gate."""
from django.test import SimpleTestCase

from app.domain.architecture.topology import (
    Evidence,
    InternalDependency,
    ProjectTopology,
    UngroundedTopology,
    check_evidence,
    clean_path,
    clean_technologies,
)
from app.domain.projects import SuggestedProject

TREE = [
    "README.md",
    "package.json",
    "apps/api-gateway/package.json",
    "apps/api-gateway/src/index.ts",
    "services/auth-service/pyproject.toml",
    "packages/shared-lib/go.mod",
]


class SuggestionsFromDiscoveryTests(SimpleTestCase):
    def test_nothing_found_suggests_nothing(self):
        self.assertEqual(SuggestedProject.from_discovery([], TREE), ())

    def test_a_single_unit_is_the_repository_itself(self):
        out = SuggestedProject.from_discovery([SuggestedProject("src", "src")], ["src/main.py"])
        self.assertEqual(out, ())

    def test_paths_are_cleaned_and_unknown_directories_dropped(self):
        out = SuggestedProject.from_discovery(
            [
                SuggestedProject("./apps/api-gateway/", "api-gateway", kind="service"),
                SuggestedProject("apps/does-not-exist", "ghost"),
                SuggestedProject("services/auth-service", "", kind="weird"),
                SuggestedProject("../escape", "x"),
            ],
            TREE,
        )
        self.assertEqual(
            [(s.path, s.name, s.kind) for s in out],
            [
                ("apps/api-gateway", "api-gateway", "service"),
                ("services/auth-service", "auth-service", "other"),  # name fallback, kind fallback
            ],
        )

    def test_the_root_is_never_suggested_and_duplicates_collapse(self):
        out = SuggestedProject.from_discovery(
            [
                SuggestedProject("packages/shared-lib", "shared-lib"),
                SuggestedProject("", "whatever the model said"),
                SuggestedProject("packages/shared-lib", "dup"),
            ],
            TREE,
        )
        self.assertEqual([(s.path, s.name) for s in out], [("packages/shared-lib", "shared-lib")])

    def test_suggestions_are_capped(self):
        tree = [f"svc{i}/main.go" for i in range(40)]
        found = [SuggestedProject(f"svc{i}", f"svc{i}") for i in range(40)]
        self.assertEqual(len(SuggestedProject.from_discovery(found, tree, limit=25)), 25)

    def test_open_suggestions_leave_out_paths_already_added(self):
        found = [SuggestedProject("apps/web", "web"), SuggestedProject("services/api", "api")]
        self.assertEqual([s.path for s in SuggestedProject.still_open(found, ["apps/web"])], ["services/api"])

    def test_technologies_are_deduped_and_capped(self):
        self.assertEqual(clean_technologies(["Go", "go", " Next.js ", ""]), ("Go", "Next.js"))
        self.assertEqual(len(clean_technologies([f"t{i}" for i in range(30)])), 20)

    def test_clean_path(self):
        for raw in ("", ".", "./", "/", " / "):
            self.assertEqual(clean_path(raw), "")
        self.assertEqual(clean_path("./apps\\web/"), "apps/web")


class RepositorySliceTests(SimpleTestCase):
    REPO = {
        "units": [
            {"path": "apps/web", "name": "web", "kind": "frontend", "technologies": ["React"]},
            {"path": "services/api", "name": "api", "kind": "service"},
        ],
        "internal": [
            {"source_path": "apps/web", "target_ref": "{repo}#services/api", "label": "REST"},
            {"source_path": "", "target_ref": "acme/other"},
        ],
        "externals": [{"source_path": "services/api", "name": "Stripe"}],
    }

    def test_a_rooted_project_gets_its_units_edges_and_tech(self):
        web = ProjectTopology.of_repository(self.REPO, "apps/web")
        self.assertEqual(web.technologies, ("React",))
        self.assertEqual(web.internal, (InternalDependency("{repo}#services/api", "REST"),))
        self.assertEqual(web.suggestions, ())

    def test_the_whole_repository_project_gets_every_unit_as_a_suggestion(self):
        root = ProjectTopology.of_repository(self.REPO, "")
        self.assertEqual([s.path for s in root.suggestions], ["apps/web", "services/api"])
        self.assertEqual(root.internal, (InternalDependency("acme/other"),))


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
        topo = ProjectTopology(
            technologies=("Go",),
            suggestions=(SuggestedProject("apps/web", "web", technologies=("React",)),),
            evidence=Evidence(tree_size=3, files_read=("go.mod",)),
        )
        self.assertEqual(ProjectTopology.from_dict(topo.to_dict()), topo)

    def test_from_dict_tolerates_missing_sections(self):
        topo = ProjectTopology.from_dict({"technologies": ["Go"]})
        self.assertEqual(topo.technologies, ("Go",))
        self.assertEqual(topo.internal, ())
        self.assertIsNone(topo.evidence.tree_size)
