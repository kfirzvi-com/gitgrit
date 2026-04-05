"""Sandbox container entrypoint.

Reads /input.json for config (platform, project_id, access_token),
creates the appropriate provider, wraps it in a ProjectContext,
loads /policy.py and calls evaluate(project), then writes the JSON result
to stdout.
"""

import json
import traceback

from project_context import ProjectContext
from providers.factory import create_provider


def main():
    try:
        with open("/input.json") as f:
            config = json.load(f)

        provider = create_provider(
            platform=config.get("platform", "mock"),
            project_id=config.get("project_id", ""),
            access_token=config.get("access_token"),
            base_url=config.get("base_url", ""),
            full_path=config.get("full_path", ""),
            mock_data=config.get("mock_data"),
        )
        project = ProjectContext(provider)

        policy_globals = {}
        with open("/policy.py") as f:
            exec(f.read(), policy_globals)

        evaluate = policy_globals.get("evaluate")
        if evaluate is None:
            raise RuntimeError("Policy does not define an evaluate() function")

        result = evaluate(project)
        print(json.dumps(result))

    except Exception:
        error_result = {
            "passed": False,
            "score": 0,
            "message": f"Policy execution error: {traceback.format_exc()}",
            "details": {"error": True},
        }
        print(json.dumps(error_result))


if __name__ == "__main__":
    main()
