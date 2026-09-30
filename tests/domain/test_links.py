"""Code-found link candidates: what the scanner picks up, what it ignores,
and how it shortlists roster targets. Pure — no database, no model."""
from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

from django.test import SimpleTestCase

from app.domain.architecture.links import (
    DEFAULT_LIMIT,
    MAX_FILE_CHARS,
    MAX_FILES_PER_COMPONENT,
    REFERENCE_KINDS,
    SNIPPET_CHARS,
    LinkCandidate,
    TargetOption,
    _image_name,
    already_covered,
    find_link_candidates,
)
from app.domain.architecture.resolve import RosterEntry, with_siblings
from app.domain.architecture.topology import (
    ComponentDecl,
    ExternalLink,
    InternalDependency,
    RepositoryTopology,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MINI = REPO_ROOT / "tests" / "fixtures" / "links" / "messy_mini"
MESSY = Path(os.environ.get("GITGRIT_MESSY_REPO", REPO_ROOT.parent / "gitgrit-demo-messy-monorepo"))
THIS_REPO = "kfirzvi-com/gitgrit-demo-messy-monorepo"

COMPONENTS = (
    ComponentDecl("", "gitgrit-demo-messy-monorepo", "frontend"),
    ComponentDecl("apps/api-gateway", "api-gateway", "service"),
    ComponentDecl("frontend/web-storefront", "web-storefront", "frontend"),
    ComponentDecl("services/auth-service", "auth-service", "service"),
    ComponentDecl("services/orders-service", "orders-service", "service"),
    ComponentDecl("services/data-pipeline", "data-pipeline", "job"),
    ComponentDecl("packages/shared-lib", "shared-lib", "library"),
    ComponentDecl("platform/backend/services/notifications", "notifications", "service"),
    ComponentDecl("deploy/terraform", "terraform", "infra"),
)
# The multi-repo demo projects that share the workspace — same names as the
# siblings, so a shortlist has to rank the sibling first.
OTHER_REPOS = ("api-gateway", "web-storefront", "auth-service", "orders-service",
               "payments-service", "shared-lib", "infra", "data-pipeline")


def roster_for(components=COMPONENTS) -> tuple[RosterEntry, ...]:
    """Built the way refresh.py builds full_roster: other repos as roots, this
    repo's components as siblings without ids."""
    others = tuple(RosterEntry(f"kfirzvi-com/gitgrit-demo-{n}", "", n, component_id=n) for n in OTHER_REPOS)
    return with_siblings(others, THIS_REPO, components)


def local_tree(root: Path):
    files = [p.relative_to(root).as_posix() for p in sorted(root.rglob("*")) if p.is_file()]

    def read_file(path: str):
        target = root / path
        if not target.is_file():
            return None
        try:
            return target.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return None

    return files, read_file


def scan(root: Path = MINI, components=COMPONENTS, **kw):
    tree, read_file = local_tree(root)
    return find_link_candidates(tree, read_file, components, roster_for(components), this_repo=THIS_REPO, **kw)


def find(scan_result, source_path: str, kind: str, reference: str) -> LinkCandidate | None:
    for c in scan_result.candidates:
        if c.key == (source_path, kind, reference.lower()):
            return c
    return None


def refs(candidate: LinkCandidate) -> list[str]:
    return [o.ref for o in candidate.options]


def fixture_line(candidate: LinkCandidate) -> str:
    """The fixture line a candidate points at (1-based ``line``)."""
    return (MINI / candidate.file).read_text(encoding="utf-8").splitlines()[candidate.line - 1]


def _candidate(**kw) -> LinkCandidate:
    base = dict(
        source_path="apps/api-gateway", file="f", line=1, code="", reference="AUTH_SERVICE_URL",
        reference_kind="env_var",
        options=(TargetOption("A", f"{THIS_REPO}#services/auth-service", "auth-service", "service"),
                 TargetOption("B", "kfirzvi-com/gitgrit-demo-auth-service", "auth-service", "component")),
        external_name="",
    )
    return LinkCandidate(**{**base, **kw})


def scan_tree(contents: dict[str, str], components, roster=None, this_repo="org/x", **kw):
    """An inline repository: ``{path: text}`` plus its components; the roster
    defaults to the components as siblings."""
    if roster is None:
        roster = with_siblings((), this_repo, components)
    return find_link_candidates(list(contents), contents.get, components, roster, this_repo=this_repo, **kw)


class MiniFixtureTests(SimpleTestCase):
    """One scan of the small messy-monorepo fixture, shared by every test here."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mini = scan()

    # --- what is found ---

    def test_env_var_in_source_shortlists_the_sibling_first(self):
        c = find(self.mini, "apps/api-gateway", "env_var", "AUTH_SERVICE_URL")
        self.assertIsNotNone(c)
        self.assertEqual(c.file, "apps/api-gateway/src/config.ts")
        self.assertIn("AUTH_SERVICE_URL", fixture_line(c))
        self.assertEqual(refs(c)[0], f"{THIS_REPO}#services/auth-service")
        self.assertIn("kfirzvi-com/gitgrit-demo-auth-service", refs(c))
        self.assertEqual(c.options[0], TargetOption("A", f"{THIS_REPO}#services/auth-service", "auth-service", "service"))
        self.assertEqual(c.external_name, "")
        self.assertIn("AUTH_SERVICE_URL", c.code)
        self.assertLessEqual(len(c.code), SNIPPET_CHARS)
        self.assertIsNotNone(find(self.mini, "apps/api-gateway", "env_var", "ORDERS_SERVICE_URL"))

    def test_generic_next_public_api_url_falls_back_to_the_api_gateway(self):
        c = find(self.mini, "frontend/web-storefront", "env_var", "NEXT_PUBLIC_API_URL")
        self.assertIsNotNone(c)
        self.assertEqual(refs(c)[0], f"{THIS_REPO}#apps/api-gateway")
        self.assertEqual(c.external_name, "gitgrit-demo")  # from https://api.gitgrit-demo.dev — Jev decides

    def test_root_env_var_points_at_api_gateway(self):
        c = find(self.mini, "", "env_var", "API_GATEWAY_URL")
        self.assertIsNotNone(c)
        self.assertEqual(refs(c)[0], f"{THIS_REPO}#apps/api-gateway")

    def test_compose_depends_on_edges(self):
        gw_auth = find(self.mini, "apps/api-gateway", "compose_depends_on", "auth-service")
        gw_orders = find(self.mini, "apps/api-gateway", "compose_depends_on", "orders-service")
        store_gw = find(self.mini, "frontend/web-storefront", "compose_depends_on", "api-gateway")
        orders_pay = find(self.mini, "services/orders-service", "compose_depends_on", "payments-service")
        self.assertTrue(gw_auth and refs(gw_auth)[0] == f"{THIS_REPO}#services/auth-service")
        self.assertTrue(gw_orders and refs(gw_orders)[0] == f"{THIS_REPO}#services/orders-service")
        self.assertTrue(store_gw and refs(store_gw)[0] == f"{THIS_REPO}#apps/api-gateway")
        self.assertTrue(orders_pay and refs(orders_pay) == ["kfirzvi-com/gitgrit-demo-payments-service"])
        self.assertEqual(gw_auth.file, "docker-compose.yml")
        self.assertIn("auth-service", fixture_line(gw_auth))
        self.assertIn("depends_on", fixture_line(gw_auth))

    def test_compose_image_shortlists_the_repo_root(self):
        c = find(self.mini, "services/orders-service", "image", "ghcr.io/kfirzvi-com/gitgrit-demo-payments-service:latest")
        self.assertIsNotNone(c)
        self.assertEqual(refs(c), ["kfirzvi-com/gitgrit-demo-payments-service"])
        self.assertEqual(c.external_name, "")

    def test_k8s_env_pointing_at_a_service_is_a_k8s_ref(self):
        c = find(self.mini, "apps/api-gateway", "k8s_ref", "auth-service")
        self.assertIsNotNone(c)
        self.assertEqual(c.file, "deploy/k8s/api-gateway.yaml")
        self.assertEqual(refs(c)[0], f"{THIS_REPO}#services/auth-service")

    def test_url_literal_in_config(self):
        c = find(self.mini, "services/orders-service", "url", "payments.gitgrit-demo.dev")
        self.assertIsNotNone(c)
        self.assertEqual(c.external_name, "gitgrit-demo")
        self.assertIn("kfirzvi-com/gitgrit-demo-payments-service", refs(c))
        internal = find(self.mini, "services/orders-service", "url", "auth-service")
        self.assertIsNotNone(internal)
        self.assertEqual(internal.external_name, "")

    def test_sdk_and_external_names(self):
        stripe = find(self.mini, "frontend/web-storefront", "sdk_client", "stripe")
        self.assertIsNotNone(stripe)
        self.assertEqual((stripe.external_name, stripe.options), ("stripe", ()))
        auth0_import = find(self.mini, "services/auth-service", "sdk_client", "auth0")
        self.assertIsNotNone(auth0_import)
        self.assertEqual(auth0_import.file, "services/auth-service/app/main.py")
        self.assertIsNotNone(find(self.mini, "platform/backend/services/notifications", "sdk_client", "sendgrid"))
        auth0_domain = find(self.mini, "", "env_var", "AUTH0_DOMAIN")
        self.assertIsNotNone(auth0_domain)
        self.assertEqual(auth0_domain.external_name, "auth0")

    def test_queue_name_links_consumer_to_producer(self):
        c = find(self.mini, "platform/backend/services/notifications", "queue_name", "gitgrit-demo-orders-events")
        self.assertIsNotNone(c)
        self.assertEqual(refs(c)[0], f"{THIS_REPO}#services/orders-service")

    # --- what is ignored ---

    def test_noise_is_absent(self):
        all_refs = {(c.source_path, c.reference.lower()) for c in self.mini.candidates}
        self.assertFalse(any(ref in ("database_url", "redis_url", "postgres", "redis") for _, ref in all_refs))
        self.assertFalse(any("expressjs" in ref or "localhost" in ref for _, ref in all_refs))
        self.assertFalse(any("payments-v1" in ref for _, ref in all_refs))  # legacy/orders-v1 belongs to nobody
        self.assertNotIn(("services/auth-service", "auth_service_url"), all_refs)  # self-reference
        self.assertNotIn(("services/auth-service", "auth-service"), all_refs)
        self.assertNotIn(("services/orders-service", "gitgrit-demo-orders-events"), all_refs)  # its own queue
        self.assertFalse(any(f.startswith(("legacy/", "apps/api-gateway/node_modules/")) for f in self.mini.files_read))
        self.assertNotIn("README.md", self.mini.files_read)
        self.assertNotIn("services/payments-service/README.md", self.mini.files_read)

    def test_files_read_lists_what_was_opened_in_order(self):
        files_read = list(self.mini.files_read)
        self.assertLessEqual(
            {"docker-compose.yml", "deploy/k8s/api-gateway.yaml", "deploy/k8s/auth-service.yaml", ".env.example",
             "apps/api-gateway/src/config.ts", "frontend/web-storefront/.env.example"},
            set(files_read),
        )
        # Structural files (compose, k8s) are opened before any component's own files.
        component_file = files_read.index("apps/api-gateway/src/config.ts")
        self.assertLess(files_read.index("docker-compose.yml"), component_file)
        self.assertLess(files_read.index("deploy/k8s/api-gateway.yaml"), component_file)
        self.assertEqual(len(files_read), len(set(files_read)))

    # --- ordering, limit, dedupe ---

    def test_ordered_by_kind_priority_then_file(self):
        kinds = [REFERENCE_KINDS.index(c.reference_kind) for c in self.mini.candidates]
        self.assertEqual(kinds, sorted(kinds))
        for kind in set(c.reference_kind for c in self.mini.candidates):
            with self.subTest(kind=kind):
                files = [(c.file, c.line) for c in self.mini.candidates if c.reference_kind == kind]
                self.assertEqual(files, sorted(files))
        self.assertEqual(self.mini.candidates[0].reference_kind, "compose_depends_on")

    def test_limit_and_dedupe(self):
        self.assertEqual(len({c.key for c in self.mini.candidates}), len(self.mini.candidates))
        self.assertEqual(len(scan(limit=3).candidates), 3)
        self.assertEqual(scan(limit=3).candidates, self.mini.candidates[:3])


class ShortlistAndSelectionTests(SimpleTestCase):
    def test_key_is_source_kind_and_lowercased_reference(self):
        c = _candidate(source_path="a", reference="AUTH_SERVICE_URL", options=())
        self.assertEqual(c.key, ("a", "env_var", "auth_service_url"))

    def test_options_are_capped_at_six_with_letter_ids(self):
        tree = ["svc/.env"]
        read = lambda p: "ORDERS_URL=http://orders:80\n"  # noqa: E731
        components = (ComponentDecl("svc", "svc"),)
        roster = (
            tuple(RosterEntry(f"org/orders-{n}", "", f"orders-{n}") for n in ("api", "worker", "ui", "cron", "etl", "bff", "cli"))
            + tuple(RosterEntry(f"org/unrelated-{i}", "", f"unrelated-{i}") for i in range(8))
            + (RosterEntry("org/x", "svc", "svc"),)
        )
        result = find_link_candidates(tree, read, components, roster, this_repo="org/x")
        (c,) = result.candidates
        self.assertEqual([o.id for o in c.options], ["A", "B", "C", "D", "E", "F"])

    def test_broken_yaml_and_binary_files_are_tolerated(self):
        tree = ["docker-compose.yml", "deploy/k8s/broken.yaml", "logo.png", "svc/.env"]
        contents = {
            "docker-compose.yml": "services:\n  a:\n    build: .\n    depends_on: [b\n",  # unterminated
            "deploy/k8s/broken.yaml": "{{ .Values.x }}: [",
            "svc/.env": "PAYMENTS_URL=https://api.stripe.com/v1\n",
        }
        components = (ComponentDecl("svc", "svc"),)
        roster = (RosterEntry("org/x", "svc", "svc"),)
        result = find_link_candidates(tree, contents.get, components, roster, this_repo="org/x")
        (c,) = result.candidates
        self.assertEqual((c.reference, c.external_name, c.options), ("PAYMENTS_URL", "stripe", ()))
        self.assertNotIn("logo.png", result.files_read)

    def test_root_manifests_belong_to_nobody_when_there_is_no_root_component(self):
        """A root ``.env`` in a repo whose root is not a component must not be
        handed to every component: that turned one root variable into a wrong
        edge per component in the messy-monorepo eval."""
        tree = [".env.example", "apps/gw/src/index.ts", "services/auth/app.py"]
        contents = {".env.example": "AUTH_URL=http://auth:8000\n", "apps/gw/src/index.ts": "", "services/auth/app.py": ""}
        components = (ComponentDecl("apps/gw", "gw"), ComponentDecl("services/auth", "auth"))
        roster = with_siblings((), "org/x", components)
        result = find_link_candidates(tree, contents.get, components, roster, this_repo="org/x")
        self.assertEqual(result.candidates, ())
        self.assertNotIn(".env.example", result.files_read)

        with_root = components + (ComponentDecl("", "x"),)
        result = find_link_candidates(tree, contents.get, with_root, roster + (RosterEntry("org/x", "", "x"),), this_repo="org/x")
        self.assertEqual([(c.source_path, c.reference) for c in result.candidates], [("", "AUTH_URL")])

    # --- limits ---

    def test_oversized_file_is_opened_but_not_scanned(self):
        contents = {"svc/.env": "AUTH_URL=http://auth:8000\n" + "#" * MAX_FILE_CHARS}
        components = (ComponentDecl("svc", "svc"), ComponentDecl("auth", "auth"))
        result = scan_tree(contents, components)
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.files_read, ("svc/.env",))

    def test_files_per_component_are_capped_in_read_order(self):
        filler = {f"svc/src/f{i:03}.py": "" for i in range(MAX_FILES_PER_COMPONENT)}
        last = {"svc/src/zzz.py": "const auth = process.env.AUTH_URL ?? 'http://auth:8000';\n"}
        components = (ComponentDecl("svc", "svc"), ComponentDecl("auth", "auth"))

        capped = scan_tree({**filler, **last}, components)
        self.assertEqual(capped.candidates, ())
        self.assertNotIn("svc/src/zzz.py", capped.files_read)
        self.assertEqual(len(capped.files_read), MAX_FILES_PER_COMPONENT)

        room = dict(filler)
        room.pop("svc/src/f000.py")
        kept = scan_tree({**room, **last}, components)
        self.assertEqual([c.reference for c in kept.candidates], ["AUTH_URL"])
        self.assertIn("svc/src/zzz.py", kept.files_read)


class OneFormatEachTests(SimpleTestCase):
    def test_compose_environment_block_in_both_forms(self):
        compose = (
            "services:\n"
            "  gw:\n"
            "    build: ./apps/gw\n"
            "    environment:\n"
            "      - PORT=3000\n"
            "      - AUTH_SERVICE_URL=http://auth-service:8000\n"
            "  web:\n"
            "    build: ./apps/web\n"
            "    environment:\n"
            "      ORDERS_URL: http://orders:8080\n"
            "      DATABASE_URL: postgres://db/x\n"
        )
        components = (
            ComponentDecl("apps/gw", "gw"), ComponentDecl("apps/web", "web"),
            ComponentDecl("services/auth-service", "auth-service"), ComponentDecl("services/orders", "orders"),
        )
        result = scan_tree({"docker-compose.yml": compose}, components)
        self.assertEqual(
            {c.key for c in result.candidates},
            {("apps/gw", "env_var", "auth_service_url"), ("apps/web", "env_var", "orders_url")},
        )
        gw_auth = find(result, "apps/gw", "env_var", "AUTH_SERVICE_URL")
        self.assertEqual(refs(gw_auth), ["org/x#services/auth-service"])
        self.assertIn("AUTH_SERVICE_URL", compose.splitlines()[gw_auth.line - 1])
        web_orders = find(result, "apps/web", "env_var", "ORDERS_URL")
        self.assertEqual(refs(web_orders), ["org/x#services/orders"])
        self.assertIn("ORDERS_URL", compose.splitlines()[web_orders.line - 1])

    def test_k8s_configmap_data_is_scanned_as_env_pairs(self):
        configmap = (
            "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: api-gateway-config\n"
            "data:\n  LOG_LEVEL: debug\n  AUTH_SERVICE_URL: http://auth-service.default.svc.cluster.local:8000\n"
        )
        components = (ComponentDecl("apps/api-gateway", "api-gateway"), ComponentDecl("services/auth-service", "auth-service"))
        result = scan_tree({"deploy/k8s/gw-config.yaml": configmap}, components)
        (c,) = result.candidates
        self.assertEqual(c.key, ("apps/api-gateway", "env_var", "auth_service_url"))
        self.assertEqual(c.file, "deploy/k8s/gw-config.yaml")
        self.assertIn("AUTH_SERVICE_URL", configmap.splitlines()[c.line - 1])
        self.assertEqual((refs(c), c.external_name), (["org/x#services/auth-service"], ""))

    def test_helm_values_yaml_belongs_to_the_charts_component(self):
        values = "replicaCount: 2\nupstreams:\n  auth: http://auth-service:8000\n"
        components = (ComponentDecl("apps/api-gateway", "api-gateway"), ComponentDecl("services/auth-service", "auth-service"))
        result = scan_tree({"deploy/helm/api-gateway/values.yaml": values}, components)
        (c,) = result.candidates
        self.assertEqual(c.key, ("apps/api-gateway", "url", "auth-service"))
        self.assertEqual((c.file, refs(c)), ("deploy/helm/api-gateway/values.yaml", ["org/x#services/auth-service"]))

    def test_queue_call_with_a_string_literal_argument(self):
        go = 'out, err := client.SendMessage(ctx, &sqs.SendMessageInput{QueueUrl: aws.String("orders-events")})\n'
        components = (ComponentDecl("svc/notify", "notify"), ComponentDecl("svc/orders", "orders"))
        result = scan_tree({"svc/notify/main.go": go}, components)
        (c,) = result.candidates
        self.assertEqual(c.key, ("svc/notify", "queue_name", "orders-events"))
        self.assertEqual(refs(c), ["org/x#svc/orders"])

    def test_grpc_dial_target_is_an_sdk_client_candidate(self):
        go = 'conn, err := grpc.Dial("orders-service:50051", grpc.WithInsecure())\n'
        components = (ComponentDecl("apps/gw", "gw"), ComponentDecl("services/orders-service", "orders-service"))
        result = scan_tree({"apps/gw/main.go": go}, components)
        (c,) = result.candidates
        self.assertEqual(c.key, ("apps/gw", "sdk_client", "orders-service"))
        self.assertEqual((refs(c), c.external_name), (["org/x#services/orders-service"], ""))

    def test_image_name_strips_tag_or_digest_only_in_the_last_segment(self):
        cases = {
            "localhost:5000/org/repo:tag": "localhost:5000/org/repo",
            "reg.io:5000/org/repo": "reg.io:5000/org/repo",
            "ghcr.io/org/repo@sha256:abc": "ghcr.io/org/repo",
            "postgres:16": "postgres",
        }
        for image, name in cases.items():
            with self.subTest(image=image):
                self.assertEqual(_image_name(image), name)

    def test_compose_image_on_a_registry_with_a_port_still_finds_the_repo(self):
        compose = (
            "services:\n  gw:\n    build: ./apps/gw\n    depends_on: [payments]\n"
            "  payments:\n    image: localhost:5000/org/payments:1.2\n"
        )
        components = (ComponentDecl("apps/gw", "gw"),)
        roster = (RosterEntry("org/x", "apps/gw", "gw"), RosterEntry("org/payments", "", "payments"))
        result = scan_tree({"docker-compose.yml": compose}, components, roster)
        image = find(result, "apps/gw", "image", "localhost:5000/org/payments:1.2")
        self.assertIsNotNone(image)
        self.assertEqual((refs(image), image.external_name), (["org/payments"], ""))


HOSTILE_COMPONENTS = (ComponentDecl("svc", "svc"), ComponentDecl("auth", "auth"), ComponentDecl("gw", "gw"))
# 3^25 paths through the alias DAG: a walker without a seen-set never finishes.
ALIAS_DAG_DEPTH = 25


def _survivor():
    """A file whose candidate must still come out next to a hostile one."""
    return {"svc/.env": "AUTH_URL=http://auth:8000\n"}


def _alias_dag(depth: int = ALIAS_DAG_DEPTH) -> str:
    return "b0: &b0 [{x: 1}]\n" + "".join(f"b{i}: &b{i} [*b{i - 1}, *b{i - 1}, *b{i - 1}]\n" for i in range(1, depth + 1))


class HostileInputTests(SimpleTestCase):
    """Guards fail by exception or by hanging, never by being slow, so these
    assert only on the outcome."""

    def assert_survivor(self, result):
        self.assertEqual([c.key for c in result.candidates], [("svc", "env_var", "auth_url")])

    def test_yaml_alias_cycles_and_dags_do_not_hang(self):
        contents = {
            **_survivor(),
            "deploy/k8s/cycle.yaml": "kind: Deployment\nmetadata: {name: gw}\nspec: &a [*a]\n",
            "deploy/k8s/ingress.yaml": "kind: Ingress\nmetadata: {name: gw}\nspec: &a [*a]\n",
            "deploy/k8s/dag.yaml": f"kind: Deployment\nmetadata: {{name: gw}}\n{_alias_dag()}spec: *b{ALIAS_DAG_DEPTH}\n",
        }
        self.assert_survivor(scan_tree(contents, HOSTILE_COMPONENTS))

    def test_compose_depends_on_alias_dag_is_not_stringified(self):
        compose = (
            f"{_alias_dag()}"
            "services:\n"
            "  gw:\n"
            "    build: ./gw\n"
            f"    depends_on: [*b{ALIAS_DAG_DEPTH}, auth]\n"
            f"    environment: [*b{ALIAS_DAG_DEPTH}, *b{ALIAS_DAG_DEPTH}]\n"
            "  auth:\n"
            f"    build: {{context: *b{ALIAS_DAG_DEPTH}}}\n"
        )
        result = scan_tree({**_survivor(), "docker-compose.yml": compose}, HOSTILE_COMPONENTS)
        self.assertEqual(
            [c.key for c in result.candidates],
            [("gw", "compose_depends_on", "auth"), ("svc", "env_var", "auth_url")],
        )

    def test_k8s_metadata_that_is_not_a_mapping_is_skipped(self):
        contents = {
            **_survivor(),
            "deploy/k8s/bad.yaml": "kind: Deployment\nmetadata: foo\nspec: {containers: [{name: 7, image: [x]}]}\n",
            "deploy/k8s/svc.yaml": "kind: Service\nmetadata: foo\n",
        }
        self.assert_survivor(scan_tree(contents, HOSTILE_COMPONENTS))

    def test_deeply_nested_yaml_is_skipped_not_fatal(self):
        deep = "[" * 2000 + "]" * 2000
        contents = {
            **_survivor(),
            "deploy/k8s/deep.yaml": f"kind: Deployment\nspec: {deep}\n",
            "docker-compose.yml": f"services: {deep}\n",
        }
        self.assert_survivor(scan_tree(contents, HOSTILE_COMPONENTS))  # PyYAML's parser gives up with RecursionError

    def test_a_huge_line_of_repeated_env_names_is_one_candidate(self):
        line = "ORDERS_URL=" * (MAX_FILE_CHARS // len("ORDERS_URL="))
        components = (ComponentDecl("svc", "svc"), ComponentDecl("orders", "orders"))
        result = scan_tree({"svc/.env": line + "\n"}, components)
        self.assertEqual([c.key for c in result.candidates], [("svc", "env_var", "orders_url")])


class SecretMaskingTests(SimpleTestCase):
    COMPONENTS = (ComponentDecl("svc", "svc"), ComponentDecl("services/auth-service", "auth-service"))

    def snippet(self, path: str, text: str) -> str:
        (c,) = scan_tree({path: text}, self.COMPONENTS).candidates
        self.assertEqual(c.reference, "AUTH_SERVICE_URL")
        return c.code

    def test_secrets_next_to_the_match_are_masked_in_the_snippet(self):
        env = (
            "STRIPE_SECRET_KEY=sk_live_abc\n"
            "AUTH_SERVICE_URL=http://svc:hunter2@auth-service:8000\n"
            "DB_PASSWORD='p4ss'\n"
            "SENDGRID_API_KEY: SG.xyz\n"
        )
        code = self.snippet("svc/.env", env)
        self.assertIn("AUTH_SERVICE_URL=http://***@auth-service:8000", code)
        self.assertIn("STRIPE_SECRET_KEY=***", code)
        self.assertIn("DB_PASSWORD=***", code)
        self.assertIn("SENDGRID_API_KEY: ***", code)
        for secret in ("sk_live_abc", "hunter2", "p4ss", "SG.xyz"):
            self.assertNotIn(secret, code)

    def test_compose_list_items_are_masked(self):
        compose = (
            "services:\n  svc:\n    build: ./svc\n    environment:\n"
            "      - DB_PASSWORD=hunter2\n"
            "      - AUTH_SERVICE_URL=http://auth-service:8000\n"
            "      - API_TOKEN: t0ps3cret\n"
        )
        code = self.snippet("docker-compose.yml", compose)
        self.assertIn("- DB_PASSWORD=***", code)
        self.assertIn("- API_TOKEN: ***", code)
        self.assertNotIn("hunter2", code)
        self.assertNotIn("t0ps3cret", code)

    def test_k8s_value_after_a_credential_name_is_masked(self):
        manifest = (
            "kind: Deployment\nmetadata: {name: svc}\nspec:\n  containers:\n    - name: svc\n      env:\n"
            "        - name: DB_PASSWORD\n"
            "          value: hunter2\n"
            "        - name: AUTH_SERVICE_URL\n"
            "          value: http://auth-service:8000\n"
            "        - name: LOG_LEVEL\n"
            "          value: debug\n"
        )
        code = self.snippet("deploy/k8s/svc.yaml", manifest)
        self.assertIn("- name: DB_PASSWORD\n          value: ***", code)
        self.assertNotIn("hunter2", code)
        self.assertIn("value: debug", code)  # only a credential name masks the value under it

    def test_a_reference_to_a_secret_is_not_masked(self):
        references = {
            "DB_PASSWORD=${DB_PASSWORD}": "${DB_PASSWORD}",
            "DB_PASSWORD=$DB_PASSWORD": "$DB_PASSWORD",
            "password: DB_PASSWORD": "DB_PASSWORD",
            'SECRET_KEY = os.environ["SECRET_KEY"]': 'os.environ["SECRET_KEY"]',
            "apiToken: process.env.API_TOKEN": "process.env.API_TOKEN",
        }
        for line, value in references.items():
            with self.subTest(line=line):
                code = self.snippet("svc/.env", f"{line}\nAUTH_SERVICE_URL=http://auth-service:8000\n")
                self.assertIn(line, code)
                self.assertIn(value, code)
        code = self.snippet("svc/.env", "password: hunter2\nAUTH_SERVICE_URL=http://auth-service:8000\n")
        self.assertIn("password: ***", code)


class AlreadyCoveredTests(SimpleTestCase):
    def test_already_covered_by_an_internal_edge(self):
        topology = RepositoryTopology(
            components=(ComponentDecl("apps/api-gateway", "api-gateway"),),
            internal=(InternalDependency("apps/api-gateway", f"{THIS_REPO}#services/auth-service"),),
        )
        self.assertTrue(already_covered(_candidate(), topology))
        sibling_form = RepositoryTopology(
            components=topology.components,
            internal=(InternalDependency("apps/api-gateway", "#Services/Auth-Service"),),
        )
        self.assertTrue(already_covered(_candidate(), sibling_form))

    def test_already_covered_by_an_external(self):
        topology = RepositoryTopology(
            components=(ComponentDecl("", "x"),),
            externals=(ExternalLink("", "Stripe API"),),
        )
        self.assertTrue(already_covered(_candidate(source_path="", options=(), external_name="stripe"), topology))

    def test_not_covered_when_source_or_target_differ(self):
        other_source = RepositoryTopology(
            components=(ComponentDecl("", "x"),),
            internal=(InternalDependency("", f"{THIS_REPO}#services/auth-service"),),
            externals=(ExternalLink("apps/api-gateway", "Stripe"),),
        )
        self.assertFalse(already_covered(_candidate(), other_source))
        other_target = RepositoryTopology(
            components=(ComponentDecl("apps/api-gateway", "api-gateway"),),
            internal=(InternalDependency("apps/api-gateway", f"{THIS_REPO}#services/orders-service"),),
        )
        self.assertFalse(already_covered(_candidate(), other_target))
        self.assertFalse(already_covered(_candidate(external_name=""), RepositoryTopology(components=())))

    def test_already_covered_ignores_loosely_written_targets(self):
        """A bare name or a slash-form target is a model guess that resolve_ref may
        send to another repository (``demo-org/auth-service`` on the messy eval);
        it must not count as covered, so the Jev stage re-checks it."""
        for loose in ("auth-service", f"{THIS_REPO}/services/auth-service", "org/x/services/auth"):
            with self.subTest(target=loose):
                topology = RepositoryTopology(
                    components=(ComponentDecl("apps/api-gateway", "api-gateway"),),
                    internal=(InternalDependency("apps/api-gateway", loose),),
                )
                self.assertFalse(already_covered(_candidate(), topology))


class DefaultLimitTests(SimpleTestCase):
    def test_settings_default_for_jev_map_max_candidates_is_the_scanner_limit(self):
        """``JEV_MAP_MAX_CANDIDATES`` falls back to the same number as the
        scanner and the Jev stage, so an unset deployment behaves like the code."""
        settings_text = (REPO_ROOT / "gitgrit" / "settings.py").read_text(encoding="utf-8")
        m = re.search(r'JEV_MAP_MAX_CANDIDATES = int\(os\.environ\.get\("JEV_MAP_MAX_CANDIDATES", "(\d+)"\)\)', settings_text)
        self.assertIsNotNone(m, "settings.py no longer reads JEV_MAP_MAX_CANDIDATES the expected way")
        self.assertEqual(int(m.group(1)), DEFAULT_LIMIT)


@unittest.skipUnless(MESSY.is_dir(), f"{MESSY} not checked out (set GITGRIT_MESSY_REPO)")
class RealMessyMonorepoTests(SimpleTestCase):
    def test_hidden_links(self):
        result = scan(MESSY)
        gw = f"{THIS_REPO}#apps/api-gateway"

        storefront = find(result, "frontend/web-storefront", "env_var", "NEXT_PUBLIC_API_URL")
        self.assertIsNotNone(storefront)
        self.assertEqual(refs(storefront)[0], gw)
        console = find(result, "", "env_var", "API_GATEWAY_URL")
        self.assertIsNotNone(console)
        self.assertEqual(refs(console)[0], gw)

        gw_auth = find(result, "apps/api-gateway", "compose_depends_on", "auth-service")
        gw_orders = find(result, "apps/api-gateway", "compose_depends_on", "orders-service")
        self.assertIsNotNone(gw_auth)
        self.assertEqual(refs(gw_auth)[0], f"{THIS_REPO}#services/auth-service")
        self.assertIsNotNone(gw_orders)
        self.assertEqual(refs(gw_orders)[0], f"{THIS_REPO}#services/orders-service")

        image = find(result, "services/orders-service", "image", "ghcr.io/kfirzvi-com/gitgrit-demo-payments-service:latest")
        self.assertIsNotNone(image)
        self.assertEqual(refs(image), ["kfirzvi-com/gitgrit-demo-payments-service"])

        self.assertFalse(
            any(f.startswith(("legacy/", "services/orders-service/vendor/")) or "node_modules" in f for f in result.files_read)
        )
