"""Parsing the repository's own map declaration (.gitgrit.yml)."""
import pytest

from app.domain.architecture.map_file import MapFileError, collect_declared, parse_map_file


def test_full_component_declaration():
    m = parse_map_file(
        "components:\n"
        "  - path: ./services/orders/\n"
        "    name: orders\n"
        "    kind: service\n"
        "    technologies: [Go]\n"
        "    depends_on: [payments, {target: org/auth, label: OAuth}]\n"
        "    infrastructure: [{name: PostgreSQL, kind: database}]\n"
        "    providers: [{name: Stripe, url: 'https://stripe.com'}]\n"
    )
    (c,) = m.components
    assert m.path == ".gitgrit.yml" and m.warnings == ()
    assert c.decl.path == "services/orders"
    assert (c.decl.name, c.decl.kind, c.decl.technologies) == ("orders", "service", ("Go",))
    assert c.has_dependencies
    assert [(d.name, d.label) for d in c.depends_on] == [("payments", ""), ("org/auth", "OAuth")]
    assert (c.infrastructure[0].name, c.infrastructure[0].kind) == ("PostgreSQL", "database")
    assert c.providers[0].url == "https://stripe.com" and c.consumers == ()


def test_empty_dependency_list_still_counts_as_declared():
    (c,) = parse_map_file("components:\n  - {path: '', depends_on: []}\n").components
    assert c.has_dependencies and c.decl.path == ""


def test_component_without_dependency_keys_is_left_to_the_model():
    (c,) = parse_map_file("components:\n  - path: api\n").components
    assert not c.has_dependencies


def test_file_without_components_declares_nothing():
    assert parse_map_file("# nothing yet\n").components == ()
    assert parse_map_file("other: 1\n").components == ()


@pytest.mark.parametrize(
    "text, error",
    [
        ("components: [oops\n", "not valid YAML"),
        ("- a\n", "top level"),
        ("components: []\n", "non-empty list"),
    ],
)
def test_file_level_problems_make_the_file_unusable(text, error):
    with pytest.raises(MapFileError, match=error):
        parse_map_file(text)


def test_a_bad_component_is_skipped_and_the_rest_kept():
    m = parse_map_file("components:\n  - name: api\n  - {path: web, depends_on: []}\n")
    assert [c.decl.path for c in m.components] == ["web"]
    assert "needs a 'path'" in m.warnings[0] and "skipped" in m.warnings[0]


@pytest.mark.parametrize(
    "entry, warning",
    [
        ("{path: api, depends_on: x}", "must be a list"),
        ("{path: api, providers: [{url: 'https://x.io'}]}", "needs a 'name'"),
        ("{path: api, providers: [{name: X, url: 'javascript:alert(1)'}]}", "http:// or https://"),
    ],
)
def test_a_bad_dependency_key_leaves_the_component_to_the_model(entry, warning):
    m = parse_map_file(f"components:\n  - {entry}\n")
    (c,) = m.components
    assert not c.has_dependencies and c.providers == ()
    assert warning in m.warnings[0]


def test_matched_keys_a_lone_surviving_declaration_by_the_root():
    m = parse_map_file("components:\n  - {path: app, depends_on: []}\n  - {path: gone, depends_on: []}\n")
    found, dropped = m.matched(["app/main.py"])
    assert found == {"": m.components[0]} and dropped == ("gone",)


def test_collect_declared_is_complete_when_every_component_declares_dependencies():
    tree = ["a/go.mod", "b/go.mod"]
    full = parse_map_file(
        "components:\n  - {path: a, depends_on: [b], providers: [Stripe]}\n  - {path: b, infrastructure: [{name: Redis, kind: cache}]}\n"
    )
    declared = collect_declared(full, tree, "mono")
    assert declared.complete and declared.missing == ()
    topo = declared.topology
    assert [c.path for c in topo.components] == ["a", "b"]
    assert [(d.source_path, d.target_ref) for d in topo.internal] == [("a", "b")]
    assert topo.evidence.map_file == ".gitgrit.yml"


def test_collect_declared_lists_components_left_to_the_model():
    tree = ["a/go.mod", "b/go.mod"]
    partial = parse_map_file("components:\n  - {path: a, depends_on: [b]}\n  - {path: b}\n")
    declared = collect_declared(partial, tree, "mono")
    assert not declared.complete and declared.missing == ("b",)
    assert [c.path for c in declared.topology.components] == ["a", "b"]
    assert [d.source_path for d in declared.topology.internal] == ["a"]


def test_collect_declared_without_components_leaves_discovery_to_the_model():
    declared = collect_declared(parse_map_file(""), ["go.mod"], "mono")
    assert not declared.complete
    assert declared.topology.components == () and declared.topology.evidence.map_file == ""


def test_deeply_nested_yaml_is_an_unusable_file_not_a_crash():
    with pytest.raises(MapFileError, match="not valid YAML"):
        parse_map_file("components:\n  - " + "[" * 5000 + "\n")


def test_docs_list_the_kinds_the_code_accepts():
    from pathlib import Path

    from app.domain.architecture.topology import COMPONENT_KINDS, INFRA_KINDS

    docs = (Path(__file__).resolve().parents[2] / "site/docs/features/architecture-map-file.md").read_text()
    assert f"# {' | '.join(COMPONENT_KINDS)}" in docs
    assert f"# kind: {' | '.join(INFRA_KINDS)}" in docs
