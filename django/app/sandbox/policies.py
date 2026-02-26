"""Hardcoded policy scripts for POC.

Each policy is a Python source string containing an evaluate(context) function
that returns a result dict with: passed, score, message, details.
"""

CHECK_README = '''
def evaluate(context):
    files = context.get("project", {}).get("files", [])
    has_readme = any(f.lower().startswith("readme") for f in files)
    return {
        "passed": has_readme,
        "score": 100 if has_readme else 0,
        "message": "README exists" if has_readme else "No README found",
        "details": {"files_checked": len(files)},
    }
'''
