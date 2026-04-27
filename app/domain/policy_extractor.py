import ast
from dataclasses import asdict, dataclass
from typing import Literal

PredicateKind = Literal["search", "match", "startswith", "endswith", "in"]

_NON_LOCAL_CALLS: frozenset[str] = frozenset(
    {"get_members", "get_contributors", "get_commits"}
)

_ALLOWED_PROJECT_CALLS: frozenset[str] = frozenset(
    {
        "get_file_content",
        "list_files",
        "get_languages",
        "get_default_branch",
        "get_topics",
        "get_metadata",
    }
)


@dataclass
class ForbiddenPattern:
    kind: PredicateKind
    value: str


@dataclass
class PolicyRules:
    watched_files: list[str]
    forbidden_patterns: list[ForbiddenPattern]
    locally_enforceable: bool
    watched_files_complete: bool
    forbidden_patterns_complete: bool


def to_dict(rules: PolicyRules) -> dict:
    return asdict(rules)


def extract_rules(code: str) -> PolicyRules:
    """Parse policy source and return the subset of enforcement data the plugin can act on.

    Literals only. Any non-literal argument to a watched predicate flips the matching
    ``*_complete`` flag to ``False`` and is not captured. ``locally_enforceable`` is
    default-deny: True only when at least one ``project.get_file_content(...)`` call exists
    AND no disallowed project API is touched.
    """
    try:
        tree = ast.parse(code, filename="<policy>")
    except SyntaxError:
        return PolicyRules(
            watched_files=[],
            forbidden_patterns=[],
            locally_enforceable=False,
            watched_files_complete=True,
            forbidden_patterns_complete=True,
        )

    watched_files: list[str] = []
    forbidden_patterns: list[ForbiddenPattern] = []
    watched_files_complete = True
    forbidden_patterns_complete = True

    has_get_file_content = False
    touches_non_local = False
    touches_unknown_project_call = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if _is_attr_on_name(func, "project"):
                attr = func.attr
                if attr in _NON_LOCAL_CALLS:
                    touches_non_local = True
                elif attr not in _ALLOWED_PROJECT_CALLS:
                    touches_unknown_project_call = True
                if attr == "get_file_content":
                    has_get_file_content = True
                    if node.args:
                        literal = _string_literal(node.args[0])
                        if literal is not None:
                            watched_files.append(literal)
                        else:
                            watched_files_complete = False
            elif _is_attr_on_name(func, "re") and func.attr in ("search", "match"):
                if node.args:
                    literal = _string_literal(node.args[0])
                    if literal is not None:
                        forbidden_patterns.append(
                            ForbiddenPattern(kind=func.attr, value=literal)
                        )
                    else:
                        forbidden_patterns_complete = False
            elif isinstance(func, ast.Attribute) and func.attr in (
                "startswith",
                "endswith",
            ):
                if node.args:
                    literal = _string_literal(node.args[0])
                    if literal is not None:
                        forbidden_patterns.append(
                            ForbiddenPattern(kind=func.attr, value=literal)
                        )
                    else:
                        forbidden_patterns_complete = False

        elif isinstance(node, ast.Compare):
            # "literal" in <expr> → Compare(left=Constant, ops=[In()]).
            # "literal" not in <expr> → Compare(ops=[NotIn()]). Policies commonly
            # phrase forbidden substrings as ``"X" not in content`` (passes when
            # absent), so treat NotIn the same as In for extraction.
            # Chained comparisons (`a in b in c`) fall through untreated.
            if len(node.ops) == 1 and isinstance(
                node.ops[0], (ast.In, ast.NotIn)
            ):
                literal = _string_literal(node.left)
                if literal is not None:
                    forbidden_patterns.append(
                        ForbiddenPattern(kind="in", value=literal)
                    )

    locally_enforceable = (
        has_get_file_content
        and not touches_non_local
        and not touches_unknown_project_call
    )

    return PolicyRules(
        watched_files=watched_files,
        forbidden_patterns=forbidden_patterns,
        locally_enforceable=locally_enforceable,
        watched_files_complete=watched_files_complete,
        forbidden_patterns_complete=forbidden_patterns_complete,
    )


def _is_attr_on_name(node: ast.AST, name: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == name
    )


def _string_literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None
