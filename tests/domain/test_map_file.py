"""Parsing the repository's own map declaration (.gitgrit.yml)."""
import pytest

from app.domain.architecture.map_file import MapFileError, declared_topology, parse_map_file


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


def test_declared_topology_needs_every_component_declared():
    tree = ["a/go.mod", "b/go.mod"]
    full = parse_map_file(
        "components:\n  - {path: a, depends_on: [b], providers: [Stripe]}\n  - {path: b, infrastructure: [{name: Redis, kind: cache}]}\n"
    )
    topo = declared_topology(full, tree, "mono")
    assert [c.path for c in topo.components] == ["a", "b"]
    assert [(d.source_path, d.target_ref) for d in topo.internal] == [("a", "b")]
    assert topo.evidence.declared and topo.evidence.map_file == ".gitgrit.yml"

    partial = parse_map_file("components:\n  - {path: a, depends_on: []}\n  - {path: b}\n")
    assert declared_topology(partial, tree, "mono") is None
