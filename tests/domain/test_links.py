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
    EVIDENCE_KIND,
    MAX_FILE_CHARS,
    MAX_FILES_PER_COMPONENT,
    PACKAGE_DEP_KIND,
    REFERENCE_KINDS,
    SNIPPET_CHARS,
    LinkCandidate,
    TargetOption,
    _image_name,
    already_covered,
    find_evidence,
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

    def test_package_dep_on_the_shared_lib_from_every_manifest_kind(self):
        shared = f"{THIS_REPO}#packages/shared-lib"
        expected = {
            # source, dependency as written, manifest, text on the line
            ("apps/api-gateway", "@gitgrit-demo/shared-lib", "apps/api-gateway/package.json", "workspace:*"),
            ("frontend/web-storefront", "@gitgrit-demo/shared-lib", "frontend/web-storefront/package.json", "file:../../packages/shared-lib"),
            ("", "@gitgrit-demo/shared-lib", "package.json", '"@gitgrit-demo/shared-lib": "*"'),
            ("services/auth-service", "shared-lib", "services/auth-service/pyproject.toml", '"shared-lib"'),
            ("services/orders-service", "demo/shared-lib", "services/orders-service/go.mod", "demo/shared-lib v0.0.0"),
        }
        for source, reference, file, text in expected:
            with self.subTest(source=source):
                c = find(self.mini, source, PACKAGE_DEP_KIND, reference)
                self.assertIsNotNone(c)
                self.assertEqual((c.file, c.reference, c.external_name), (file, reference, ""))
                self.assertIn(text, fixture_line(c))
                # The manifest resolved the target, so the sibling is the only option:
                # no same-named other repo for Jev to pick by name.
                self.assertEqual(c.options, (TargetOption("A", shared, "shared-lib", "library"),))
                self.assertIn(reference, c.code)
        found = {(c.source_path, c.reference) for c in self.mini.candidates if c.reference_kind == PACKAGE_DEP_KIND}
        self.assertEqual(found, {(s, r) for s, r, _, _ in expected})  # express, next, sqs… are not links

    def test_package_dep_is_emitted_right_after_image(self):
        self.assertEqual(REFERENCE_KINDS.index(PACKAGE_DEP_KIND), REFERENCE_KINDS.index("image") + 1)
        kinds = [c.reference_kind for c in self.mini.candidates]
        self.assertLess(kinds.index("image"), kinds.index(PACKAGE_DEP_KIND))
        self.assertLess(kinds.index(PACKAGE_DEP_KIND), kinds.index("k8s_ref"))

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


LIB_COMPONENTS = (ComponentDecl("apps/gw", "gw", "service"), ComponentDecl("packages/lib", "lib", "library"))
LIB_REF = "org/x#packages/lib"


def package_deps(result):
    return [(c.source_path, c.reference, c.file, c.line) for c in result.candidates if c.reference_kind == PACKAGE_DEP_KIND]


class PackageDepTests(SimpleTestCase):
    """A dependency in a component's own manifest that names a sibling, per
    manifest kind; third-party libraries and self-dependencies are nothing."""

    def assert_lib_dep(self, result, reference: str, file: str, line: int, source: str = "apps/gw"):
        self.assertEqual(package_deps(result), [(source, reference, file, line)])
        (c,) = [c for c in result.candidates if c.reference_kind == PACKAGE_DEP_KIND]
        self.assertEqual((refs(c), c.external_name), ([LIB_REF], ""))
        self.assertEqual(c.options[0], TargetOption("A", LIB_REF, "lib", "library"))
        return c

    def test_package_json_by_name_and_by_path(self):
        by_name = {
            "packages/lib/package.json": '{"name": "@org/lib"}\n',
            "apps/gw/package.json": (
                '{\n  "name": "@org/gw",\n  "dependencies": {\n    "express": "^4.0.0",\n'
                '    "@org/lib": "workspace:*"\n  },\n  "devDependencies": {"@org/gw": "*"}\n}\n'
            ),
        }
        self.assert_lib_dep(scan_tree(by_name, LIB_COMPONENTS), "@org/lib", "apps/gw/package.json", 5)
        by_path = {
            "packages/lib/package.json": '{"name": "something-else"}\n',
            "apps/gw/package.json": '{"dependencies": {"shared": "file:../../packages/lib", "left-pad": "link:../../vendor/x"}}\n',
        }
        self.assert_lib_dep(scan_tree(by_path, LIB_COMPONENTS), "shared", "apps/gw/package.json", 1)

    def test_go_mod_require_by_module_path_and_replace_by_directory(self):
        by_module = {
            "packages/lib/go.mod": "module github.com/org/x/packages/lib\n\ngo 1.22\n",
            "apps/gw/go.mod": (
                "module github.com/org/x/apps/gw\n\ngo 1.22\n\nrequire (\n"
                "\tgithub.com/aws/aws-sdk-go-v2 v1.30.0\n"
                "\tgithub.com/org/x/packages/lib v0.0.0 // indirect\n)\n"
            ),
        }
        self.assert_lib_dep(scan_tree(by_module, LIB_COMPONENTS), "github.com/org/x/packages/lib", "apps/gw/go.mod", 7)
        by_replace = {
            "packages/lib/go.mod": "module example.com/renamed\n",
            "apps/gw/go.mod": "module gw\n\nrequire example.com/lib v1.0.0\n\nreplace example.com/lib v1.0.0 => ../../packages/lib\n",
        }
        self.assert_lib_dep(scan_tree(by_replace, LIB_COMPONENTS), "example.com/lib", "apps/gw/go.mod", 5)
        no_sibling = {"apps/gw/go.mod": "module gw\n\nrequire example.com/lib v1.0.0\n\nreplace example.com/lib => example.com/fork v1.1.0\n"}
        self.assertEqual(package_deps(scan_tree(no_sibling, LIB_COMPONENTS)), [])

    def test_pyproject_dependencies_uv_sources_and_poetry(self):
        pep621 = {
            "packages/lib/pyproject.toml": '[project]\nname = "Org_Shared.Lib"\n',
            "apps/gw/pyproject.toml": '[project]\nname = "gw"\ndependencies = [\n  "fastapi>=0.110",\n  "org-shared-lib>=1",\n]\n',
        }
        self.assert_lib_dep(scan_tree(pep621, LIB_COMPONENTS), "org-shared-lib", "apps/gw/pyproject.toml", 5)
        uv = {
            "packages/lib/pyproject.toml": '[project]\nname = "unrelated"\n',
            "apps/gw/pyproject.toml": '[project]\nname = "gw"\ndependencies = ["shared"]\n\n[tool.uv.sources]\nshared = { path = "../../packages/lib" }\n',
        }
        self.assert_lib_dep(scan_tree(uv, LIB_COMPONENTS), "shared", "apps/gw/pyproject.toml", 3)
        poetry = {
            "packages/lib/pyproject.toml": '[tool.poetry]\nname = "lib"\n',
            "apps/gw/pyproject.toml": '[tool.poetry]\nname = "gw"\n\n[tool.poetry.dependencies]\npython = "^3.12"\nlib = { path = "../../packages/lib", develop = true }\n',
        }
        self.assert_lib_dep(scan_tree(poetry, LIB_COMPONENTS), "lib", "apps/gw/pyproject.toml", 6)

    def test_requirements_editable_path_and_distribution_name(self):
        editable = {"apps/gw/requirements-dev.txt": "# tools\npytest>=8\n-e ../../packages/lib[extra]\n"}
        c = self.assert_lib_dep(scan_tree(editable, LIB_COMPONENTS), "../../packages/lib", "apps/gw/requirements-dev.txt", 3)
        self.assertIn("apps/gw/requirements-dev.txt", c.file)
        by_name = {
            "packages/lib/pyproject.toml": '[project]\nname = "org-lib"\n',
            "apps/gw/requirements.txt": "-r base.txt\nrequests==2.32.0\norg_lib==1.0  # sibling\n",
        }
        self.assert_lib_dep(scan_tree(by_name, LIB_COMPONENTS), "org_lib", "apps/gw/requirements.txt", 3)

    def test_cargo_path_dependency(self):
        cargo = {
            "packages/lib/Cargo.toml": '[package]\nname = "lib"\n',
            "apps/gw/Cargo.toml": '[package]\nname = "gw"\n\n[dependencies]\nserde = "1"\nlib = { path = "../../packages/lib" }\n',
        }
        self.assert_lib_dep(scan_tree(cargo, LIB_COMPONENTS), "lib", "apps/gw/Cargo.toml", 6)

    def test_third_party_and_self_dependencies_are_nothing(self):
        contents = {
            "packages/lib/package.json": '{"name": "@org/lib", "dependencies": {"@org/lib": "*", "zod": "^3"}}\n',
            "apps/gw/package.json": '{"dependencies": {"express": "^4", "react": "*"}}\n',
            "apps/gw/go.mod": "module gw\nrequire github.com/stripe/stripe-go v78.0.0\n",
        }
        self.assertEqual(package_deps(scan_tree(contents, LIB_COMPONENTS)), [])

    def test_a_path_that_lands_outside_every_sibling_is_nothing(self):
        contents = {
            "apps/gw/package.json": '{"dependencies": {"tooling": "file:../../tools/x", "root": "file:../.."}}\n',
        }
        self.assertEqual(package_deps(scan_tree(contents, LIB_COMPONENTS)), [])
        with_root = LIB_COMPONENTS + (ComponentDecl("", "x"),)
        result = scan_tree(contents, with_root)
        self.assertEqual([(s, r) for s, r, _, _ in package_deps(result)], [("apps/gw", "root")])  # ``../..`` is the root itself

    def test_a_path_inside_a_sibling_resolves_to_it(self):
        contents = {"apps/gw/pyproject.toml": '[tool.uv.sources]\nlibpy = { path = "../../packages/lib/python" }\n'}
        self.assert_lib_dep(scan_tree(contents, LIB_COMPONENTS), "libpy", "apps/gw/pyproject.toml", 2)

    def test_broken_json_and_toml_are_tolerated(self):
        contents = {
            "packages/lib/package.json": '{"name": "@org/lib"',
            "packages/lib/pyproject.toml": "[project\nname = ",
            "apps/gw/package.json": '{"dependencies": {"@org/lib": ',
            "apps/gw/pyproject.toml": "dependencies = [",
            "apps/gw/Cargo.toml": "[dependencies\n",
            "apps/gw/.env": "LIB_URL=http://lib:8000\n",
        }
        result = scan_tree(contents, LIB_COMPONENTS)
        self.assertEqual([c.key for c in result.candidates], [("apps/gw", "env_var", "lib_url")])

    def test_dependency_lines_are_scanned_only_for_files_a_component_owns(self):
        contents = {
            "packages/lib/package.json": '{"name": "@org/lib"}\n',
            "package.json": '{"dependencies": {"@org/lib": "*"}}\n',  # no root component: nobody's manifest
            "docs/package.json": '{"dependencies": {"@org/lib": "*"}}\n',
        }
        self.assertEqual(package_deps(scan_tree(contents, LIB_COMPONENTS)), [])


AUTH = ComponentDecl("services/auth-service", "auth-service", "service")
GW = ComponentDecl("apps/api-gateway", "api-gateway", "service")
AUTH_OPTIONS = (TargetOption("A", f"{THIS_REPO}#services/auth-service", "auth-service", "service"),)


def evidence(contents: dict[str, str], component=GW, tokens=("auth-service",), options=AUTH_OPTIONS, external_name=""):
    return find_evidence(list(contents), contents.get, component, tokens, options, external_name, this_repo=THIS_REPO)


class FindEvidenceTests(SimpleTestCase):
    """One evidence candidate for an edge the LLM claimed: the first line in
    the component that mentions the target."""

    def test_found_in_a_config_file_with_the_scanner_snippet(self):
        contents = {
            "apps/api-gateway/src/index.ts": "import express from 'express';\n",
            "apps/api-gateway/config/services.yaml": "upstreams:\n  auth: http://auth-service:8000\n  orders: http://orders-service:8080\n",
        }
        c = evidence(contents)
        self.assertIsNotNone(c)
        self.assertEqual((c.source_path, c.file, c.line), ("apps/api-gateway", "apps/api-gateway/config/services.yaml", 2))
        self.assertEqual((c.reference, c.reference_kind), ("auth-service", EVIDENCE_KIND))
        self.assertEqual((c.options, c.external_name), (AUTH_OPTIONS, ""))
        self.assertEqual(c.code, "upstreams:\n  auth: http://auth-service:8000\n  orders: http://orders-service:8080")
        self.assertEqual(c.key, ("apps/api-gateway", EVIDENCE_KIND, "auth-service"))

    def test_config_files_are_read_before_source_and_the_first_line_wins(self):
        contents = {
            "apps/api-gateway/src/config.ts": "export const auth = process.env.AUTH_SERVICE_URL;\n",
            "apps/api-gateway/.env.example": "PORT=3000\nAUTH_SERVICE_URL=http://auth-service:8000\n",
        }
        c = evidence(contents)
        self.assertEqual((c.file, c.line, c.reference), ("apps/api-gateway/.env.example", 2, "AUTH_SERVICE"))

    def test_token_variants_and_word_boundaries(self):
        cases = {
            # line, token -> matched text (None: no evidence)
            ("AUTH_SERVICE_URL=http://x\n", "auth-service"): "AUTH_SERVICE",
            ("auth.service.local\n", "auth_service"): "auth.service",
            ("upstream: auth-service-legacy\n", "auth-service"): "auth-service",  # a longer name built on it still mentions it
            ("client = oauth.Client()\n", "auth"): None,
            ("authservice = 1\n", "auth-service"): None,
            ("x = Stripe(key)\n", "stripe"): "Stripe",
            ("image: ghcr.io/kfirzvi-com/gitgrit-demo-payments-service:latest\n", "gitgrit-demo-payments-service"): "gitgrit-demo-payments-service",
        }
        for (line, token), expected in cases.items():
            with self.subTest(line=line, token=token):
                c = evidence({"apps/api-gateway/config.yaml": line}, tokens=(token,))
                self.assertEqual(c.reference if c else None, expected)

    def test_longest_token_wins_and_empty_tokens_are_nothing(self):
        line = "image: ghcr.io/org/gitgrit-demo-payments-service:latest\n"
        c = evidence({"apps/api-gateway/config.yaml": line}, tokens=("payments", "gitgrit-demo-payments-service", ""))
        self.assertEqual(c.reference, "gitgrit-demo-payments-service")
        self.assertIsNone(evidence({"apps/api-gateway/config.yaml": line}, tokens=("", " ")))
        self.assertIsNone(evidence({"apps/api-gateway/config.yaml": line}, tokens=("x" * 3000,)))

    def test_none_when_the_component_never_mentions_the_target(self):
        contents = {
            "apps/api-gateway/src/config.ts": "export const orders = process.env.ORDERS_SERVICE_URL;\n",
            "services/auth-service/app/main.py": "SELF = 'auth-service'\n",  # another component's file
            "README.md": "The gateway calls auth-service.\n",  # not scannable
        }
        self.assertIsNone(evidence(contents))

    def test_skips_and_caps_match_the_scanner(self):
        contents = {
            "apps/api-gateway/node_modules/x/index.js": "fetch('http://auth-service:8000')\n",
            "apps/api-gateway/vendor/y/config.json": '{"auth-service": 1}\n',
            "apps/api-gateway/fixtures/case.json": '{"auth-service": 1}\n',
            "apps/api-gateway/package-lock.json": '{"auth-service": 1}\n',
            "apps/api-gateway/big.json": '{"auth-service": 1}' + "#" * MAX_FILE_CHARS,
        }
        self.assertIsNone(evidence(contents))
        root_skips = {"docs/auth.md": "auth-service\n", "legacy/old.py": "x = 'auth-service'\n", "scripts/x.py": "auth-service\n"}
        self.assertIsNone(evidence(root_skips, component=ComponentDecl("", "root")))

    def test_compose_and_k8s_files_count_after_the_components_own_files(self):
        contents = {
            "docker-compose.yml": "services:\n  api-gateway:\n    build: ./apps/api-gateway\n    depends_on: [auth-service]\n",
            "deploy/k8s/gw.yaml": "kind: Deployment\nmetadata: {name: api-gateway}\n",
            "apps/api-gateway/src/index.ts": "import express from 'express';\n",
        }
        c = evidence(contents)
        self.assertEqual((c.file, c.line, c.reference), ("docker-compose.yml", 4, "auth-service"))
        own_first = {**contents, "apps/api-gateway/config.yaml": "auth: http://auth-service:8000\n"}
        self.assertEqual(evidence(own_first).file, "apps/api-gateway/config.yaml")

    def test_snippet_masks_secrets_and_userinfo(self):
        env = (
            "STRIPE_SECRET_KEY=sk_live_abc\n"
            "AUTH_SERVICE_URL=http://svc:hunter2@auth-service:8000\n"
            "DB_PASSWORD='p4ss'\n"
        )
        c = evidence({"apps/api-gateway/.env": env})
        self.assertEqual(c.line, 2)
        self.assertIn("AUTH_SERVICE_URL=http://***@auth-service:8000", c.code)
        self.assertIn("STRIPE_SECRET_KEY=***", c.code)
        self.assertIn("DB_PASSWORD=***", c.code)
        for secret in ("sk_live_abc", "hunter2", "p4ss"):
            self.assertNotIn(secret, c.code)

    def test_a_comment_mention_is_kept_only_when_nothing_else_mentions_the_target(self):
        """Terraform: line 1 is a comment naming the infra repo, line 6 the
        remote-state key. The key must be the evidence, or Jev answers
        "inactive" for a real dependency."""
        tf = (
            "# Shared VPC/subnets are owned by kfirzvi-com/gitgrit-demo-infra.\n"
            "data \"terraform_remote_state\" \"network\" {\n"
            "  backend = \"s3\"\n"
            "  config = {\n"
            "    bucket = \"demo-tfstate\"\n"
            "    key    = \"gitgrit-demo-infra/network.tfstate\"\n"
            "  }\n}\n"
        )
        terraform = ComponentDecl("deploy/terraform", "terraform", "infra")
        c = evidence({"deploy/terraform/network.tf": tf}, component=terraform, tokens=("gitgrit-demo-infra", "infra"))
        self.assertEqual((c.file, c.line), ("deploy/terraform/network.tf", 6))
        only_comment = evidence(
            {"deploy/terraform/README.tf": "# see kfirzvi-com/gitgrit-demo-infra\n"},
            component=terraform, tokens=("gitgrit-demo-infra",),
        )
        self.assertEqual((only_comment.file, only_comment.line), ("deploy/terraform/README.tf", 1))

    def test_the_matched_line_itself_is_secret_masked(self):
        contents = {"apps/api-gateway/.env": "AUTH_SERVICE_SECRET=hunter2\nAUTH_SERVICE_URL=http://auth-service:8000\n"}
        c = evidence(contents)
        self.assertEqual(c.line, 1)  # the first mention is the secret line
        self.assertNotIn("hunter2", c.code)
        self.assertIn("AUTH_SERVICE_SECRET=", c.code)

    def test_a_root_component_does_not_borrow_nested_components_files(self):
        contents = {
            "package.json": '{"name": "console"}\n',
            "services/auth-service/app/main.py": "SELF = 'auth-service'\n",
        }
        root = ComponentDecl("", "console", "frontend")
        borrowed = find_evidence(list(contents), contents.get, root, ("auth-service",), AUTH_OPTIONS, this_repo=THIS_REPO)
        self.assertIsNotNone(borrowed)  # alone, the root owns every file
        scoped = find_evidence(
            list(contents), contents.get, root, ("auth-service",), AUTH_OPTIONS,
            this_repo=THIS_REPO, components=(root, AUTH),
        )
        self.assertIsNone(scoped)

    def test_external_target_passes_its_name_through(self):
        c = evidence({"apps/api-gateway/package.json": '{"dependencies": {"@stripe/stripe-js": "^4"}}\n'},
                     tokens=("stripe",), options=(), external_name="stripe")
        self.assertEqual((c.reference, c.options, c.external_name), ("stripe", (), "stripe"))


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

    def test_shared_lib_package_deps_match_the_golden_edges(self):
        """Every golden ``→ packages/shared-lib`` edge has a ``package_dep``
        candidate whose first option is the sibling library."""
        result = scan(MESSY)
        shared = f"{THIS_REPO}#packages/shared-lib"
        golden_sources = {"", "apps/api-gateway", "frontend/web-storefront", "services/auth-service",
                          "services/orders-service", "services/data-pipeline", "platform/backend/services/notifications"}
        by_source = {c.source_path: c for c in result.candidates if c.reference_kind == PACKAGE_DEP_KIND and refs(c)[0] == shared}
        self.assertEqual(set(by_source), golden_sources)
        for source, c in by_source.items():
            with self.subTest(source=source):
                self.assertTrue(c.file.startswith(source), c.file)
                self.assertEqual(c.options, (TargetOption("A", shared, "shared-lib", "library"),))
                self.assertEqual(c.external_name, "")
        self.assertEqual(
            {c.reference for c in by_source.values()},
            {"@gitgrit-demo/shared-lib", "gitgrit-demo-shared-lib", "github.com/kfirzvi-com/gitgrit-demo-monorepo/packages/shared-lib"},
        )
        # Nothing else in a manifest is a link: the other-repo payments client and the third-party libraries.
        others = [c for c in result.candidates if c.reference_kind == PACKAGE_DEP_KIND and refs(c)[0] != shared]
        self.assertEqual(others, [])
