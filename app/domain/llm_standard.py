"""Whether a standard asks for the ``llm``: its ``evaluate`` takes an ``llm``
parameter. Only those standards spend AI tokens, so only they are held back
when a model's budget stops runs."""
from __future__ import annotations

import ast


def asks_for_llm(code: str) -> bool:
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate":
            names = [a.arg for a in node.args.args + node.args.kwonlyargs]
            return "llm" in names
    return False
