"""Pure rules for the ``.gitgrit.yml`` map file: what is valid, what it parses
to, and that a written topology reads back the same."""
from django.test import SimpleTestCase

from app.domain.architecture.map_file import InvalidMapFile, dump_map_file, parse_map_file
from app.domain.architecture.topology import (
    INBOUND,
    OUTBOUND,
    ComponentDecl,
    ExternalLink,
    InfrastructureResource,
    InternalDependency,
    RepositoryTopology,
)

TREE = [
    "README.md",
    "apps/api-gateway/package.json",
    "services/auth-service/pyproject.toml",
]

VALID = """\
version: 1
components:
  - path: ./apps/api-gateway/
    name: api-gateway
    kind: service
    description: Public API.
    technologies: [Express, zod]
    dependencies:
      internal:
        - target: "#services/auth-service"
          label: OAuth
        - target: group/sub/api#apps/core
      infrastructure:
        - name: Redis
          kind: cache
        - name: Search
      external_providers:
        - name: Stripe
          url: https://stripe.com
          label: payments
      external_consumers:
        - name: Partner portal
  - path: services/auth-service
"""


def _body(components: str) -> str:
    return "version: 1\ncomponents:\n" + components


class ParseMapFileTests(SimpleTestCase):
    def test_parses_components_and_dependencies_by_cleaned_path(self):
        topo = parse_map_file(VALID, TREE)

        self.assertEqual(
            topo.components,
            (
                ComponentDecl("apps/api-gateway", "api-gateway", "service", "Public API.", ("Express", "zod")),
                ComponentDecl("services/auth-service", ""),
            ),
        )
        self.assertEqual(
            topo.internal,
            (
                InternalDependency("apps/api-gateway", "#services/auth-service", "OAuth"),
                InternalDependency("apps/api-gateway", "group/sub/api#apps/core"),
            ),
        )
        self.assertEqual(
            topo.infrastructure,
            (
                InfrastructureResource("apps/api-gateway", "Redis", "cache"),
                InfrastructureResource("apps/api-gateway", "Search", "other"),
            ),
        )
        self.assertEqual(
            topo.externals,
            (
                ExternalLink("apps/api-gateway", "Stripe", OUTBOUND, "https://stripe.com", "payments"),
                ExternalLink("apps/api-gateway", "Partner portal", INBOUND),
            ),
        )

    def test_root_component_needs_no_directory(self):
        topo = parse_map_file(_body("  - path: ''\n"), [])
        self.assertEqual(topo.components, (ComponentDecl("", ""),))

    def test_invalid_files_name_the_broken_rule(self):
        cases = {
            "version: 1\ncomponents: [\n": "not valid YAML",
            "- a\n- b\n": "top level must be a mapping",
            "version: 2\ncomponents:\n  - path: ''\n": "'version' must be 1",
            "version: 1\ncomponents: []\n": "non-empty list",
            _body("".join(f"  - path: p{i}\n" for i in range(26))): "at most 25",
            _body("  - name: web\n"): "'path' is required",
            _body("  - path: 3\n"): "'path' must be a string",
            _body("  - path: ''\n    kind: daemon\n"): "kind must be one of",
            _body("  - path: ''\n    technologies: Python\n"): "list of strings",
            _body("  - path: apps/ghost\n"): "'apps/ghost' is not a directory",
            _body("  - path: apps/api-gateway/package.json\n"): "is not a directory",
            _body("  - path: apps/api-gateway\n  - path: apps/api-gateway/\n"): "duplicate path",
            _body("  - path: ''\n  - path: .\n"): "duplicate path ''",
            _body("  - path: ''\n    dependencies: [x]\n"): "must be a mapping",
            _body("  - path: ''\n    dependencies:\n      externals: []\n"): "unknown key(s) externals",
            _body("  - path: ''\n    dependencies:\n      internal:\n        - label: x\n"): "'target' is required",
            _body("  - path: ''\n    dependencies:\n      internal:\n        - target: api\n"): "must be owner/repo",
            _body("  - path: ''\n    dependencies:\n      internal:\n        - target: org/a#b#c\n"): "must be owner/repo",
            _body("  - path: ''\n    dependencies:\n      infrastructure:\n        - kind: cache\n"): "'name' is required",
            _body("  - path: ''\n    dependencies:\n      infrastructure:\n        - name: X\n          kind: other\n"): "kind must be one of database",
            _body("  - path: ''\n    dependencies:\n      external_consumers:\n        - url: x\n"): "'name' is required",
            _body("  - path: ''\n    dependencies:\n      external_providers: Stripe\n"): "must be a list",
        }
        for text, reason in cases.items():
            with self.subTest(reason):
                with self.assertRaises(InvalidMapFile) as ctx:
                    parse_map_file(text, TREE)
                self.assertIn(reason, str(ctx.exception))


class DumpMapFileTests(SimpleTestCase):
    def test_round_trip(self):
        topo = RepositoryTopology(
            components=(
                ComponentDecl("", "mono", "other", "", ()),
                ComponentDecl("apps/api-gateway", "api-gateway", "service", "Public API.", ("Express",)),
                ComponentDecl("services/auth-service", "auth-service", "service", "", ("FastAPI",)),
            ),
            internal=(
                InternalDependency("apps/api-gateway", "#services/auth-service", "OAuth"),
                InternalDependency("apps/api-gateway", "org/api"),
            ),
            externals=(
                ExternalLink("apps/api-gateway", "Stripe", OUTBOUND, "https://stripe.com", "payments"),
                ExternalLink("apps/api-gateway", "Partner portal", INBOUND, "", "webhooks"),
            ),
            infrastructure=(InfrastructureResource("services/auth-service", "PostgreSQL", "database", "users DB"),),
        )

        text = dump_map_file(topo)

        self.assertEqual(parse_map_file(text, TREE), topo)
        self.assertTrue(text.startswith("version: 1\ncomponents:\n- path: ''\n"))

    def test_infra_kind_outside_the_file_set_is_left_out(self):
        topo = RepositoryTopology(
            components=(ComponentDecl("", "web"),),
            infrastructure=(InfrastructureResource("", "Elasticsearch", "other"),),
        )

        text = dump_map_file(topo)

        self.assertEqual(text.count("kind:"), 1)  # the component's only
        self.assertEqual(parse_map_file(text, []).infrastructure, topo.infrastructure)
