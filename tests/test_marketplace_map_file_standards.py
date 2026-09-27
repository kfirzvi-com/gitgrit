"""The map-file marketplace standards pass their own ``test_cases`` and agree
with the parser the map uses.

The sandbox runs ``evaluate(project)`` against a mock fed with the test
case's ``input``; this runs the same contract in-process so a fixture edit
that breaks its own examples fails here, not in a customer's workspace.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.domain.architecture.map_file import MapFileError, parse_map_file

FIXTURES = Path(__file__).resolve().parent.parent / "app" / "fixtures" / "marketplace" / "standards"
PACK_STANDARDS = (
    "map-file-declares-components",
    "map-file-covers-deployables",
    "map-file-dependencies-declared",
)


class _FakeProject:
    def __init__(self, data: dict):
        self._data = data

    def list_files(self):
        return list(self._data.get("list_files", []))

    def get_file_content(self, path):
        return self._data.get("get_file_content", {}).get(path)


def _spec(slug):
    return yaml.safe_load((FIXTURES / f"{slug}.yaml").read_text())


def _evaluate(code: str, data: dict) -> dict:
    namespace: dict = {}
    exec(compile(code, "<standard>", "exec"), namespace)  # noqa: S102 — fixture code, in-process test
    return namespace["evaluate"](_FakeProject(data))


@pytest.mark.parametrize(
    "slug, case",
    [(slug, case) for slug in PACK_STANDARDS for case in _spec(slug)["test_cases"]],
    ids=lambda v: v if isinstance(v, str) else v["name"],
)
def test_standard_passes_its_own_test_case(slug, case):
    result = _evaluate(_spec(slug)["code"], case.get("input", {}))
    assert (result["passed"], result["score"]) == (case["expected"]["passed"], case["expected"]["score"]), result["message"]


@pytest.mark.parametrize("slug", PACK_STANDARDS)
def test_every_passing_example_is_a_file_the_map_reads_without_warnings(slug):
    for case in _spec(slug)["test_cases"]:
        text = case.get("input", {}).get("get_file_content", {}).get(".gitgrit.yml")
        if text is None:
            continue
        if case["expected"]["passed"]:
            m = parse_map_file(text)
            assert m.components and m.warnings == (), case["name"]
        elif "YAML" in case["name"]:
            with pytest.raises(MapFileError):
                parse_map_file(text)


def test_declares_components_fails_every_file_the_parser_warns_about():
    code = _spec("map-file-declares-components")["code"]
    for entry in (
        "{path: api, providers: Stripe}",
        "{path: api, depends_on: [{label: x}]}",
        "{path: api, consumers: [{name: X, url: 'data:text/html,x'}]}",
        "{path: api, technologies: [{a: b}]}",
        "{path: api, name: [x]}",
        "{name: api}",
    ):
        text = f"components:\n  - {entry}\n"
        assert parse_map_file(text).warnings, entry
        result = _evaluate(code, {"list_files": [".gitgrit.yml", "api/go.mod"], "get_file_content": {".gitgrit.yml": text}})
        assert (result["passed"], result["score"]) == (False, 0), entry


def _shared_block(slug):
    code = _spec(slug)["code"]
    start = code.index("# --- shared by the three")
    return code[start : code.index("# --- end shared ---")]


def test_the_shared_helpers_are_identical_in_all_three_standards():
    blocks = {slug: _shared_block(slug) for slug in PACK_STANDARDS}
    assert len(set(blocks.values())) == 1, "edit the shared block in all three standards"


def test_the_shared_constants_match_the_app():
    from app.domain.architecture.map_file import DEPENDENCY_KEYS, MAP_FILE_NAMES
    from app.domain.architecture.topology import COMPONENT_KINDS, INFRA_KINDS, clean_path

    ns: dict = {}
    exec(compile(_shared_block(PACK_STANDARDS[0]), "<shared>", "exec"), ns)  # noqa: S102
    assert ns["MAP_FILES"] == MAP_FILE_NAMES
    assert ns["KINDS"] == COMPONENT_KINDS
    assert ns["INFRA_KINDS"] == INFRA_KINDS
    assert ns["DEP_KEYS"] == DEPENDENCY_KEYS
    for p in ("", ".", "./a/b/", "/a", "a/b"):  # ordinary paths; only _clean also resolves ".." for compose
        assert ns["_clean"](p) == clean_path(p), p


@pytest.mark.parametrize("slug", PACK_STANDARDS)
def test_deeply_nested_yaml_fails_the_standard_instead_of_crashing_it(slug):
    deep = "components:\n  - " + "[" * 5000 + "\n"
    files = [".gitgrit.yml", "api/go.mod", "docker-compose.yml"]
    result = _evaluate(
        _spec(slug)["code"],
        {"list_files": files, "get_file_content": {".gitgrit.yml": deep, "docker-compose.yml": deep}},
    )
    assert result["passed"] is False
    assert "not valid YAML" in result["message"]


def test_dependencies_declared_skips_a_deeply_nested_compose_file():
    files = [".gitgrit.yml", "api/go.mod", "docker-compose.yml"]
    result = _evaluate(
        _spec("map-file-dependencies-declared")["code"],
        {
            "list_files": files,
            "get_file_content": {
                ".gitgrit.yml": "components:\n  - {path: '', depends_on: []}\n",
                "docker-compose.yml": "services:\n  a: " + "[" * 5000 + "\n",
            },
        },
    )
    assert result["passed"] is True, result["message"]


def test_declares_components_rejects_an_unknown_infrastructure_kind():
    text = "components:\n  - {path: '', infrastructure: [{name: PostgreSQL, kind: databse}]}\n"
    result = _evaluate(
        _spec("map-file-declares-components")["code"],
        {"list_files": [".gitgrit.yml", "go.mod"], "get_file_content": {".gitgrit.yml": text}},
    )
    assert (result["passed"], result["score"]) == (False, 0)
    assert "kind 'databse'" in result["message"]


def test_missing_file_message_prints_a_file_the_map_can_read():
    result = _evaluate(
        _spec("map-file-declares-components")["code"],
        {"list_files": ["services/orders/go.mod", "services/orders/Dockerfile", "apps/web/package.json"]},
    )
    suggested = result["details"]["suggested_gitgrit_yml"]
    paths = [c.decl.path for c in parse_map_file(suggested).components]
    assert paths == ["apps/web", "services/orders"]


def test_pack_lists_every_map_file_standard():
    packs = yaml.safe_load((FIXTURES.parent / "packs.yaml").read_text())
    pack = next(p for p in packs if p["slug"] == "architecture-map-ready")
    assert set(pack["standards"]) == set(PACK_STANDARDS)
