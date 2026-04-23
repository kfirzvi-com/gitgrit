import ast


def validate_policy_code(code: str) -> None:
    """Raise ValueError if code has a syntax error or missing evaluate(project) function."""
    try:
        tree = ast.parse(code, filename="<policy>")
    except SyntaxError as e:
        raise ValueError(f"Syntax error in policy code: {e}") from e

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate":
            if len(node.args.args) < 1:
                raise ValueError("evaluate() must accept at least one argument (project)")
            return

    raise ValueError("Policy code must define an evaluate(project) function")
