"""The three ``.gitgrit.yml`` marketplace standards (map file exists / valid /
up to date).

* Every ``test_cases`` entry in the fixtures runs through the real sandbox
  code path (``ProjectContext`` over the mock provider) and must match its
  ``expected`` keys exactly, like the standard editor's "Run tests" button.
* ``gitgrit-map-file-exists`` hands developers the same instructions the map
  LLM gets. Its copied prompts must equal the prompts in ``llm_inference``
  after the adaptations below, so a prompt change can't silently desync.
* ``gitgrit-map-file-valid`` re-implements the pipeline's parser inside the
  sandbox; it must accept and reject the same files as ``parse_map_file``.
"""
import re
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from app.domain.architecture.map_file import InvalidMapFile, parse_map_file
from app.infrastructure.topology.llm_inference import _DEPENDENCY_PROMPT, _DISCOVERY_PROMPT

ROOT = Path(__file__).resolve().parents[1]
SANDBOX_DIR = ROOT / "sandbox_image"
STANDARDS_DIR = ROOT / "app" / "fixtures" / "marketplace" / "standards"
SLUGS = ("gitgrit-map-file-exists", "gitgrit-map-file-valid", "gitgrit-map-file-up-to-date")

if str(SANDBOX_DIR) not in sys.path:
    sys.path.insert(0, str(SANDBOX_DIR))

from project_context import ProjectContext  # noqa: E402
from providers.mock import MockProvider  # noqa: E402

# The only edits allowed between the LLM prompts and the copies in
# gitgrit-map-file-exists: the developer's AI tool writes a file instead of
# returning a structured result, and it has no roster, so it is told the ref
# syntax instead. Each ``old`` must still appear exactly once in the prompt.
_STOP = "When you have enough evidence, stop calling tools and return the structured result."
DISCOVERY_ADAPTATIONS = (
    (_STOP, "When you have enough evidence, write the components into .gitgrit.yml in the format above."),
)
DEPENDENCY_ADAPTATIONS = (
    (
        "only use the components listed in the roster, and return the component's "
        "exact ref as the target (a repository's full_path for its root component, "
        "full_path#path for a component inside a monorepo). Sibling components of "
        "this repository are in the roster too — a call to another service in the "
        "same repository IS an internal dependency.",
        "only use components GitGrit knows — repositories connected to your GitGrit "
        "workspace and the other components of this repository — and write the "
        "component's exact GitGrit ref as the target: owner/repo for a repository's "
        "root component, owner/repo#path for a component inside a monorepo, and "
        "#path for a sibling component of this repository. A call to another "
        "service in the same repository IS an internal dependency.",
    ),
    ("NEVER list a roster component here", "NEVER list a workspace component here"),
    (_STOP, "When you have enough evidence, write the result under this component's `dependencies` in .gitgrit.yml."),
)


def adapt(prompt: str, adaptations) -> str:
    for old, new in adaptations:
        assert prompt.count(old) == 1, f"prompt no longer contains: {old!r}"
        prompt = prompt.replace(old, new)
    return prompt


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _fixture(slug: str) -> dict:
    return yaml.safe_load((STANDARDS_DIR / f"{slug}.yaml").read_text())


def _evaluate(code: str, mock_data: dict) -> dict:
    namespace: dict = {}
    exec(code, namespace)
    return namespace["evaluate"](ProjectContext(MockProvider("test", mock_data)))


def _cases():
    for slug in SLUGS:
        data = _fixture(slug)
        for case in data["test_cases"]:
            yield pytest.param(data["code"], case, id=f"{slug}: {case['name']}")


@pytest.mark.parametrize("code,case", list(_cases()))
def test_fixture_test_cases(code, case):
    result = _evaluate(code, case["input"])

    assert not result.get("details", {}).get("error"), result
    assert {k: result.get(k) for k in case["expected"]} == case["expected"], result["message"]


def test_fixtures_are_push_and_manual():
    for slug in SLUGS:
        data = _fixture(slug)
        assert data["slug"] == slug
        assert data["criteria"]["events"] == ["push", "manual"]


def test_exists_standard_copies_the_llm_prompts():
    namespace: dict = {}
    exec(_fixture("gitgrit-map-file-exists")["code"], namespace)

    assert _normalise(namespace["DISCOVERY_PROMPT"]) == _normalise(
        adapt(_DISCOVERY_PROMPT, DISCOVERY_ADAPTATIONS)
    )
    assert _normalise(namespace["DEPENDENCY_PROMPT"]) == _normalise(
        adapt(_DEPENDENCY_PROMPT, DEPENDENCY_ADAPTATIONS)
    )


def test_exists_standard_failure_message_carries_the_instructions():
    namespace: dict = {}
    exec(_fixture("gitgrit-map-file-exists")["code"], namespace)

    result = namespace["evaluate"](ProjectContext(MockProvider("test", {"list_files": ["README.md"]})))

    assert not result["passed"]
    for text in (namespace["DISCOVERY_PROMPT"], namespace["DEPENDENCY_PROMPT"], "version: 1"):
        assert text in result["message"]


# --- gitgrit-map-file-valid agrees with the pipeline's parser -----------------------

TREE = [
    "README.md",
    "apps/api/pyproject.toml",
    "apps/web/package.json",
    "apps/web/dist/index.js",
    "infra/main.tf",
]

VALID = """
version: 1
components:
  - path: ""
    kind: service
    technologies: [Python]
  - path: ./apps/api/
    name: api
    dependencies:
      internal:
        - target: acme/billing
        - target: group/sub/repo#svc
          label: REST
        - target: "#apps/web"
      infrastructure:
        - name: PostgreSQL
          kind: database
      external_providers:
        - name: Stripe
          url: https://stripe.com
      external_consumers:
        - name: Partner portal
  - path: infra
    kind: infra
"""

MAP_FILES = {
    "valid": VALID,
    "valid, only root": "version: 1\ncomponents:\n  - path: ''\n",
    "not yaml": "version: 1\ncomponents: [\n",
    "nested too deep": "components: " + "[" * 600 + "]" * 600 + "\n",
    "top level is a list": "- path: ''\n",
    "wrong version": "version: 2\ncomponents:\n  - path: ''\n",
    "no components": "version: 1\ncomponents: []\n",
    "too many components": "version: 1\ncomponents:\n"
    + "  - path: ''\n" * 26,
    "component not a mapping": "version: 1\ncomponents:\n  - apps/api\n",
    "path missing": "version: 1\ncomponents:\n  - name: api\n",
    "path not a string": "version: 1\ncomponents:\n  - path: 3\n",
    "path not a directory": "version: 1\ncomponents:\n  - path: apps/nope\n",
    "path is a file": "version: 1\ncomponents:\n  - path: README.md\n",
    "path in a skipped folder": "version: 1\ncomponents:\n  - path: apps/web/dist\n",
    "path too long": "version: 1\ncomponents:\n  - path: " + "a" * 1025 + "\n",
    "version true": "version: true\ncomponents:\n  - path: ''\n",
    "version 1.0": "version: 1.0\ncomponents:\n  - path: ''\n",
    "empty kind": "version: 1\ncomponents:\n  - path: ''\n    kind:\n",
    "unknown component key": "version: 1\ncomponents:\n  - path: ''\n    dependancies: {}\n",
    "extra top-level key (YAML anchor)": "base: &b {kind: service}\nversion: 1\ncomponents:\n  - <<: *b\n    path: ''\n",
    "duplicate after cleaning": "version: 1\ncomponents:\n  - path: apps/api\n  - path: ./apps/api/\n",
    "bad kind": "version: 1\ncomponents:\n  - path: ''\n    kind: database\n",
    "technologies not strings": "version: 1\ncomponents:\n  - path: ''\n    technologies: [1]\n",
    "technologies not a list": "version: 1\ncomponents:\n  - path: ''\n    technologies: Python\n",
    "name not a string": "version: 1\ncomponents:\n  - path: ''\n    name: [a]\n",
    "dependencies not a mapping": "version: 1\ncomponents:\n  - path: ''\n    dependencies: [x]\n",
    "unknown dependency key": "version: 1\ncomponents:\n  - path: ''\n    dependencies:\n      libraries: []\n",
    "internal not a list": "version: 1\ncomponents:\n  - path: ''\n    dependencies:\n      internal: acme/x\n",
    "internal without target": "version: 1\ncomponents:\n  - path: ''\n    dependencies:\n      internal:\n        - label: REST\n",
    "bad target": "version: 1\ncomponents:\n  - path: ''\n    dependencies:\n      internal:\n        - target: billing\n",
    "infra without name": "version: 1\ncomponents:\n  - path: ''\n    dependencies:\n      infrastructure:\n        - kind: cache\n",
    "infra kind other": "version: 1\ncomponents:\n  - path: ''\n    dependencies:\n      infrastructure:\n        - name: Redis\n          kind: other\n",
    "bad infra kind": "version: 1\ncomponents:\n  - path: ''\n    dependencies:\n      infrastructure:\n        - name: Redis\n          kind: stream\n",
    "provider without name": "version: 1\ncomponents:\n  - path: ''\n    dependencies:\n      external_providers:\n        - url: https://x.io\n",
    "label not a string": "version: 1\ncomponents:\n  - path: ''\n    dependencies:\n      external_consumers:\n        - name: X\n          label: [a]\n",
}


@pytest.mark.parametrize("name", list(MAP_FILES))
def test_valid_standard_agrees_with_pipeline_parser(name):
    text = textwrap.dedent(MAP_FILES[name])
    try:
        # The pipeline parses against every file (RepoToolbox.all_files).
        parse_map_file(text, TREE)
        pipeline_ok = True
    except InvalidMapFile:
        pipeline_ok = False

    result = _evaluate(
        _fixture("gitgrit-map-file-valid")["code"],
        {"list_files": TREE + [".gitgrit.yml"], "get_file_content": {".gitgrit.yml": text}},
    )

    assert result["passed"] is pipeline_ok, result["message"]
    if not pipeline_ok:
        assert result["details"]["violations"]


# --- gitgrit-map-file-up-to-date bounds its API calls --------------------------------


class _CountingProvider(MockProvider):
    def __init__(self, data):
        super().__init__("test", data)
        self.dated: list[str] = []

    def get_file_last_commit_date(self, path):
        self.dated.append(path)
        return super().get_file_last_commit_date(path)


def test_up_to_date_standard_caps_date_queries():
    manifests = [f"services/s{i:02}/package.json" for i in range(40)]
    provider = _CountingProvider(
        {
            "list_files": [".gitgrit.yml", "docker-compose.yml", *manifests],
            "get_file_content": {".gitgrit.yml": "version: 1\ncomponents:\n  - path: ''\n"},
            "get_file_last_commit_date": {".gitgrit.yml": "2026-09-01T00:00:00Z"},
        }
    )
    namespace: dict = {}
    exec(_fixture("gitgrit-map-file-up-to-date")["code"], namespace)

    result = namespace["evaluate"](ProjectContext(provider))

    assert result["passed"]
    assert len(provider.dated) == namespace["MAX_DATE_QUERIES"] + 1  # + the map file
    assert provider.dated[1] == "docker-compose.yml"  # root-level files first
    assert result["details"]["dependency_files"] == 41
    assert "were not checked" in result["details"]["dates_note"]


# --- gitgrit-map-file-up-to-date edge cases ------------------------------------------

OLD_DATE, NEW_DATE = "2026-09-01T00:00:00Z", "2026-09-20T00:00:00Z"
TWO_APPS = "version: 1\ncomponents:\n  - path: apps/api\n  - path: apps/web\n"
ROOT_ONLY = "version: 1\ncomponents:\n  - path: ''\n"


def _up_to_date(files, map_text, dates=None):
    return _evaluate(
        _fixture("gitgrit-map-file-up-to-date")["code"],
        {
            "list_files": files,
            "get_file_content": {".gitgrit.yml": map_text},
            "get_file_last_commit_date": dates or {},
        },
    )


def test_up_to_date_skips_tool_folders_in_the_coverage_check():
    result = _up_to_date(
        [
            ".gitgrit.yml",
            "apps/api/pyproject.toml",
            "apps/web/package.json",
            ".devcontainer/Dockerfile",
            ".github/actions/setup/package.json",
        ],
        TWO_APPS,
    )

    assert result["passed"], result["message"]


@pytest.mark.parametrize(
    "map_date,manifest_date,passed",
    [
        ("2026-09-10T00:00:00", NEW_DATE, False),  # no time zone = UTC
        ("2026-09-30T00:00:00", NEW_DATE, True),
        (1757462400, NEW_DATE, True),  # not a string = unknown, check skipped
        (OLD_DATE, 1757462400, True),
    ],
)
def test_up_to_date_handles_odd_dates(map_date, manifest_date, passed):
    result = _up_to_date(
        [".gitgrit.yml", "package.json"],
        ROOT_ONLY,
        {".gitgrit.yml": map_date, "package.json": manifest_date},
    )

    assert result["passed"] is passed, result["message"]


def test_up_to_date_handles_a_map_nested_too_deep():
    result = _up_to_date([".gitgrit.yml"], "components: " + "[" * 600 + "]" * 600 + "\n")

    assert result["passed"] is False
    assert "no readable component list" in result["message"]


def test_up_to_date_handles_no_file_list():
    result = _evaluate(_fixture("gitgrit-map-file-up-to-date")["code"], {"list_files": None})

    assert result["passed"] is False
    assert "No .gitgrit.yml" in result["message"]


@pytest.mark.parametrize(
    "path,counted",
    [
        ("src/charts/theme.yml", False),  # a charting library, not Helm
        ("templates/greenvalley.template", False),  # "env" inside a word
        ("charts/api/templates/deployment.yaml", True),
        ("charts/api/values.yaml", True),
        ("k8s/deployment.yaml", True),
        ("config/.env.staging.example", True),
        ("env.template", True),
    ],
)
def test_up_to_date_dependency_files(path, counted):
    result = _up_to_date(
        [".gitgrit.yml", path], ROOT_ONLY, {".gitgrit.yml": OLD_DATE, path: NEW_DATE}
    )

    assert (not result["passed"]) is counted, result["message"]


def test_valid_standard_constants_match_the_pipeline():
    from app.domain.architecture import map_file, topology

    namespace: dict = {}
    exec(_fixture("gitgrit-map-file-valid")["code"], namespace)

    assert namespace["MAX_COMPONENTS"] == topology.MAX_COMPONENTS
    assert namespace["MAX_PATH"] == topology.MAX_PATH
    assert namespace["COMPONENT_KINDS"] == topology.COMPONENT_KINDS
    assert namespace["INFRA_KINDS"] == topology.INFRA_KINDS
    assert namespace["COMPONENT_KEYS"] == map_file.COMPONENT_KEYS
    assert namespace["DEPENDENCY_KEYS"] == map_file.DEPENDENCY_KEYS
    assert namespace["TARGET"].pattern == map_file._TARGET.pattern
    assert map_file.VERSION == 1  # the standard checks ``version`` against 1


def test_exists_standard_rules_name_the_pipeline_rules():
    from app.domain.architecture import map_file, topology

    namespace: dict = {}
    exec(_fixture("gitgrit-map-file-exists")["code"], namespace)
    rules = _normalise(namespace["RULES"])

    assert f"at most {topology.MAX_COMPONENTS} entries" in rules
    assert f"at most {topology.MAX_PATH} characters" in rules
    for words in (topology.COMPONENT_KINDS, topology.INFRA_KINDS, map_file.COMPONENT_KEYS, map_file.DEPENDENCY_KEYS):
        assert ", ".join(words) in rules, words
