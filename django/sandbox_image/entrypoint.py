"""Sandbox container entrypoint.

Reads /input.json for context, loads /policy.py and calls evaluate(context),
then writes the JSON result to stdout.
"""

import json
import sys
import traceback


def main():
    try:
        with open("/input.json") as f:
            context = json.load(f)

        policy_globals = {}
        with open("/policy.py") as f:
            exec(f.read(), policy_globals)

        evaluate = policy_globals.get("evaluate")
        if evaluate is None:
            raise RuntimeError("Policy does not define an evaluate() function")

        result = evaluate(context)
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
