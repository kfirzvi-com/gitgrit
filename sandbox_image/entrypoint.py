"""Sandbox container entrypoint.

Reads /input.json for config (platform, project_id, access_token, and an
optional llm_roles map), creates the appropriate provider, wraps it in a
ProjectContext, loads /standard.py and calls evaluate(...), then writes the JSON
result to stdout.

Standard signature is resolved by parameter name: the first parameter is always
the project; a parameter named ``llm`` receives the LLM object, and one named
``log`` receives the run's StandardLogger. So all of these are valid:
    evaluate(project)
    evaluate(project, llm)
    evaluate(project, log)
    evaluate(project, llm, log)

stdout is the result channel: the host parses it as a single JSON document.
Anything else written there (standard prints, or LLM libraries like litellm that
emit banners to stdout) would corrupt that channel, so we redirect stdout to
stderr during execution and emit only the final JSON on the real stdout. The
captured log is attached to the result as ``logs`` (even on error).
"""

import inspect
import json
import sys
import time
import traceback

from standard_log import StandardLogger
from project_context import ProjectContext
from providers.factory import create_provider


def _first_line(message):
    return str(message).splitlines()[0] if str(message).strip() else ""


def _describe_result(result):
    if not isinstance(result, dict):
        return f"evaluate returned {type(result).__name__}, expected a dict"
    return (
        f"evaluate returned passed={result.get('passed')} "
        f"score={result.get('score')} message={_first_line(result.get('message', ''))!r}"
    )


def _status_word(result):
    if not isinstance(result, dict):
        return "error"
    details = result.get("details")
    if isinstance(details, dict) and details.get("error"):
        return "error"
    return "passed" if result.get("passed") else "failed"


def _run(config, logger):
    platform = config.get("platform", "mock")
    target = config.get("full_path") or config.get("project_id") or ""
    logger.info(f"run started: platform={platform} project={target}")

    provider = create_provider(
        platform=platform,
        project_id=config.get("project_id", ""),
        access_token=config.get("access_token"),
        base_url=config.get("base_url", ""),
        full_path=config.get("full_path", ""),
        ref=config.get("ref", ""),
        mock_data=config.get("mock_data"),
    )
    project = ProjectContext(provider)
    logger.info("project context ready")

    # Only pull in the LLM stack (litellm) when the workspace has roles
    # configured — deterministic standards stay fast and dependency-free.
    llm = None
    standard_globals = {}
    if config.get("llm_roles"):
        from llm import LLM, StandardVerdict

        llm = LLM(config["llm_roles"], project, logger=logger)
        standard_globals["StandardVerdict"] = StandardVerdict

    with open("/standard.py") as f:
        exec(f.read(), standard_globals)

    evaluate = standard_globals.get("evaluate")
    if evaluate is None:
        raise RuntimeError("Standard does not define an evaluate() function")

    # First parameter is the project; inject llm/log by parameter name.
    params = list(inspect.signature(evaluate).parameters)
    kwargs = {}
    for name in params[1:]:
        if name == "llm":
            if llm is None:
                raise RuntimeError(
                    "This standard requires an LLM, but no LLM role is configured "
                    "for this workspace. Configure one under "
                    "Workspace Settings → LLM."
                )
            kwargs["llm"] = llm
        elif name == "log":
            kwargs["log"] = logger

    signature = ", ".join(["project", *kwargs])
    logger.info(f"calling evaluate({signature})")
    started = time.monotonic()
    result = evaluate(project, **kwargs)
    elapsed_ms = int((time.monotonic() - started) * 1000)

    if isinstance(result, dict):
        logger.info(f"{_describe_result(result)} in {elapsed_ms} ms")
    else:
        logger.error(f"{_describe_result(result)} in {elapsed_ms} ms")

    # Surface token usage for visibility (foundation for future budgets).
    if llm is not None and isinstance(result, dict):
        details = result.setdefault("details", {})
        if isinstance(details, dict):
            details["llm_usage"] = llm.usage

    return result


def main():
    logger = StandardLogger()
    real_stdout = sys.stdout
    sys.stdout = sys.stderr  # keep standard/LLM chatter off the result channel
    try:
        with open("/input.json") as f:
            config = json.load(f)
        result = _run(config, logger)
    except Exception:
        tb = traceback.format_exc()
        logger.error(f"standard execution raised an exception\n{tb}")
        result = {
            "passed": False,
            "score": 0,
            "message": f"Standard execution error: {tb}",
            "details": {"error": True},
        }
    finally:
        sys.stdout = real_stdout

    logger.info(f"run finished: {_status_word(result)}")
    if isinstance(result, dict):
        result.setdefault("logs", logger.entries)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
