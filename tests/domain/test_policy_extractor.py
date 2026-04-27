from app.domain.policy_extractor import (
    ForbiddenPattern,
    extract_rules,
    to_dict,
)


class TestWatchedFiles:
    def test_captures_literal_file_path(self):
        code = """
def evaluate(project):
    content = project.get_file_content("README.md")
    return {"passed": content is not None, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.watched_files == ["README.md"]
        assert rules.watched_files_complete is True

    def test_captures_multiple_literal_paths(self):
        code = """
def evaluate(project):
    a = project.get_file_content("a.py")
    b = project.get_file_content("b.py")
    return {"passed": bool(a and b), "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert sorted(rules.watched_files) == ["a.py", "b.py"]
        assert rules.watched_files_complete is True

    def test_non_literal_path_flips_flag(self):
        code = """
def evaluate(project):
    path = "README.md"
    c = project.get_file_content(path)
    return {"passed": True, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.watched_files == []
        assert rules.watched_files_complete is False


class TestPredicateKinds:
    def test_re_search_literal(self):
        code = """
import re
def evaluate(project):
    c = project.get_file_content("f.py")
    return {"passed": re.search("TODO", c) is None, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.forbidden_patterns == [
            ForbiddenPattern(kind="search", value="TODO")
        ]

    def test_re_match_literal(self):
        code = """
import re
def evaluate(project):
    c = project.get_file_content("f.py")
    return {"passed": re.match("^#!", c) is None, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.forbidden_patterns == [
            ForbiddenPattern(kind="match", value="^#!")
        ]

    def test_startswith_literal(self):
        code = """
def evaluate(project):
    c = project.get_file_content("f.py") or ""
    return {"passed": not c.startswith("# OLD"), "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.forbidden_patterns == [
            ForbiddenPattern(kind="startswith", value="# OLD")
        ]

    def test_endswith_literal(self):
        code = """
def evaluate(project):
    c = project.get_file_content("f.py") or ""
    return {"passed": not c.endswith("DRAFT"), "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.forbidden_patterns == [
            ForbiddenPattern(kind="endswith", value="DRAFT")
        ]

    def test_in_literal_on_left(self):
        # Regression guard: ast.Compare/ast.In is easy to miss if walker only inspects ast.Call.
        code = """
def evaluate(project):
    c = project.get_file_content("f.py") or ""
    return {"passed": "FIXME" not in c, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.forbidden_patterns == [
            ForbiddenPattern(kind="in", value="FIXME")
        ]

    def test_re_search_in_parens_still_captured(self):
        code = """
import re
def evaluate(project):
    c = project.get_file_content("f.py") or ""
    return {"passed": re.search(("TODO"), c) is None, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.forbidden_patterns == [
            ForbiddenPattern(kind="search", value="TODO")
        ]


class TestIncompleteExtraction:
    def test_re_search_string_concat_flips_flag(self):
        code = """
import re
def evaluate(project):
    c = project.get_file_content("f.py")
    return {"passed": re.search("foo" + "bar", c) is None, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.forbidden_patterns == []
        assert rules.forbidden_patterns_complete is False

    def test_re_search_variable_flips_flag(self):
        code = """
import re
def evaluate(project):
    pat = "TODO"
    c = project.get_file_content("f.py")
    return {"passed": re.search(pat, c) is None, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.forbidden_patterns == []
        assert rules.forbidden_patterns_complete is False

    def test_re_search_fstring_flips_flag(self):
        code = """
import re
def evaluate(project):
    name = "foo"
    c = project.get_file_content("f.py")
    return {"passed": re.search(f"{name}", c) is None, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.forbidden_patterns == []
        assert rules.forbidden_patterns_complete is False

    def test_re_search_format_call_flips_flag(self):
        code = """
import re
def evaluate(project):
    c = project.get_file_content("f.py")
    return {"passed": re.search("todo_{}".format("x"), c) is None, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.forbidden_patterns == []
        assert rules.forbidden_patterns_complete is False

    def test_startswith_variable_flips_flag(self):
        code = """
def evaluate(project):
    prefix = "X"
    c = project.get_file_content("f.py") or ""
    return {"passed": not c.startswith(prefix), "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.forbidden_patterns == []
        assert rules.forbidden_patterns_complete is False


class TestLocallyEnforceable:
    def test_true_when_only_allowed_apis_and_file_content_present(self):
        code = """
def evaluate(project):
    c = project.get_file_content("README.md")
    langs = project.get_languages()
    return {"passed": True, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.locally_enforceable is True

    def test_false_when_policy_uses_get_members(self):
        code = """
def evaluate(project):
    c = project.get_file_content("README.md")
    members = project.get_members()
    return {"passed": len(members) > 0, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.locally_enforceable is False

    def test_false_when_policy_uses_get_contributors(self):
        code = """
def evaluate(project):
    c = project.get_file_content("README.md")
    people = project.get_contributors()
    return {"passed": True, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.locally_enforceable is False

    def test_false_when_policy_uses_unknown_project_api(self):
        code = """
def evaluate(project):
    c = project.get_file_content("README.md")
    something = project.something_new("x")
    return {"passed": True, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.locally_enforceable is False

    def test_false_when_no_get_file_content_call(self):
        code = """
def evaluate(project):
    files = project.list_files()
    return {"passed": len(files) > 0, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.locally_enforceable is False

    def test_import_without_call_does_not_flip(self):
        # Imports alone shouldn't flip locally_enforceable — only actual call sites do.
        code = """
from something import get_members  # noqa
def evaluate(project):
    c = project.get_file_content("README.md")
    return {"passed": True, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.locally_enforceable is True


class TestPartialPolicies:
    def test_watched_files_complete_and_patterns_incomplete(self):
        # Plan §1 regression guard: one dimension incomplete must NOT disable the other.
        code = """
import re
def evaluate(project):
    c = project.get_file_content("config.yaml")
    needle = "SECRET"
    return {"passed": re.search(needle, c) is None, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.watched_files == ["config.yaml"]
        assert rules.watched_files_complete is True
        assert rules.forbidden_patterns == []
        assert rules.forbidden_patterns_complete is False
        assert rules.locally_enforceable is True

    def test_patterns_complete_and_watched_files_incomplete(self):
        code = """
def evaluate(project):
    path = "x"
    c = project.get_file_content(path) or ""
    return {"passed": "FIXME" not in c, "score": 100, "message": "", "details": {}}
"""
        rules = extract_rules(code)
        assert rules.watched_files == []
        assert rules.watched_files_complete is False
        assert rules.forbidden_patterns == [
            ForbiddenPattern(kind="in", value="FIXME")
        ]
        assert rules.forbidden_patterns_complete is True
        assert rules.locally_enforceable is True


class TestDefensive:
    def test_syntax_error_returns_non_enforceable_block(self):
        rules = extract_rules("def evaluate(project):\n    return !!!")
        assert rules.locally_enforceable is False
        assert rules.watched_files == []
        assert rules.forbidden_patterns == []

    def test_to_dict_produces_plain_dict_with_kind_tagged_patterns(self):
        code = """
def evaluate(project):
    c = project.get_file_content("f.py") or ""
    return {"passed": "bad" not in c, "score": 100, "message": "", "details": {}}
"""
        d = to_dict(extract_rules(code))
        assert d["watched_files"] == ["f.py"]
        assert d["forbidden_patterns"] == [{"kind": "in", "value": "bad"}]
        assert d["locally_enforceable"] is True
        assert d["watched_files_complete"] is True
        assert d["forbidden_patterns_complete"] is True
