"""Default policy catalog (DEPRECATED).

These hardcoded policies are no longer used by the PolicyEngine, which now
loads tenant-specific policies from the database. This list is retained as
reference examples for seeding new tenants.

Use Policy model objects (via admin or API) instead.
"""

# DEPRECATED: No longer imported by PolicyEngine.
# Retained as seed data / reference examples.
DEFAULT_POLICIES = [
    {
        "id": "check_readme",
        "name": "Check README",
        "events": ["push"],
        "code": """\
def evaluate(project):
    files = project.list_files()
    has_readme = any(f.lower().startswith("readme") for f in files)
    return {
        "passed": has_readme,
        "score": 100 if has_readme else 0,
        "message": "README exists" if has_readme else "No README found",
        "details": {"files_checked": len(files)},
    }
""",
    },
    {
        "id": "check_ci",
        "name": "Check CI Configuration",
        "events": ["push"],
        "code": """\
def evaluate(project):
    files = project.list_files()
    ci_patterns = [
        ".github/workflows/",
        ".gitlab-ci.yml",
        "Jenkinsfile",
        ".circleci/",
        ".travis.yml",
    ]
    found = [f for f in files if any(f.startswith(p) or f == p for p in ci_patterns)]
    has_ci = len(found) > 0
    return {
        "passed": has_ci,
        "score": 100 if has_ci else 0,
        "message": "CI configuration found" if has_ci else "No CI configuration found",
        "details": {"ci_files": found},
    }
""",
    },
    {
        "id": "check_dockerfile",
        "name": "Check Dockerfile",
        "events": ["push"],
        "code": """\
def evaluate(project):
    files = project.list_files()
    dockerfiles = [f for f in files if f == "Dockerfile" or f.startswith("Dockerfile.")]
    has_dockerfile = len(dockerfiles) > 0
    return {
        "passed": has_dockerfile,
        "score": 100 if has_dockerfile else 0,
        "message": "Dockerfile found" if has_dockerfile else "No Dockerfile found",
        "details": {"dockerfiles": dockerfiles},
    }
""",
    },
    {
        # LLM-based policy: takes a second `llm` argument and evaluates a
        # subjective standard. Requires a workspace LLM provider + the
        # `reasoning` role configured under Workspace Settings → LLM.
        # `PolicyVerdict` is injected into scope by the sandbox runtime.
        "id": "llm_documentation_quality",
        "name": "Documentation Quality (LLM)",
        "events": ["push"],
        "code": """\
def evaluate(project, llm):
    verdict = llm.reasoning.evaluate(
        instructions=(
            "Assess whether this repository's documentation is genuinely useful "
            "to a new contributor. Inspect the README and any docs yourself. "
            "A repo passes only if a newcomer could set it up and contribute "
            "without asking the team. List concrete gaps as violations."
        ),
        response_model=PolicyVerdict,
    )
    return {
        "passed": verdict.passed,
        "score": 100 if verdict.passed else 0,
        "message": verdict.reason,
        "details": {"violations": verdict.violations},
    }
""",
    },
]
