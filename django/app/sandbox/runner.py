"""Sandbox runner — executes policy code in a gVisor-sandboxed Docker container."""

import json
import logging
import tempfile
from pathlib import Path

import docker
from django.conf import settings

logger = logging.getLogger(__name__)


class SandboxRunner:
    def __init__(self):
        self.client = docker.from_env()
        self.config = settings.SANDBOX

    def run(self, policy_code: str, context: dict) -> dict:
        """Run a policy script against the given context in a sandboxed container.

        Args:
            policy_code: Python source defining an evaluate(context) function.
            context: Dict passed to the policy as input.

        Returns:
            Policy result dict with passed, score, message, details.
        """
        tmp_dir = tempfile.mkdtemp(prefix="gitgud-sandbox-")
        policy_path = Path(tmp_dir) / "policy.py"
        input_path = Path(tmp_dir) / "input.json"
        container = None

        try:
            policy_path.write_text(policy_code)
            input_path.write_text(json.dumps(context))

            runtime = self._get_runtime()
            container_kwargs = {
                "image": self.config["IMAGE"],
                "volumes": {
                    str(policy_path): {"bind": "/policy.py", "mode": "ro"},
                    str(input_path): {"bind": "/input.json", "mode": "ro"},
                },
                "network_mode": "none",
                "read_only": True,
                "tmpfs": {"/tmp": "size=16m"},
                "mem_limit": self.config["MEMORY_LIMIT"],
                "nano_cpus": int(self.config["CPU_LIMIT"] * 1e9),
                "cap_drop": ["ALL"],
                "detach": True,
            }

            if runtime:
                container_kwargs["runtime"] = runtime

            container = self.client.containers.run(**container_kwargs)
            result = container.wait(timeout=self.config["TIMEOUT"])

            stdout = container.logs(stdout=True, stderr=False).decode()
            stderr = container.logs(stdout=False, stderr=True).decode()

            if stderr:
                logger.warning("Sandbox stderr: %s", stderr)

            exit_code = result.get("StatusCode", -1)
            if exit_code != 0:
                logger.error(
                    "Sandbox exited with code %d. stderr: %s", exit_code, stderr
                )

            return json.loads(stdout)

        except json.JSONDecodeError:
            logger.error("Failed to parse sandbox output: %s", stdout)
            return {
                "passed": False,
                "score": 0,
                "message": "Failed to parse policy output",
                "details": {"error": True},
            }
        except Exception as exc:
            logger.exception("Sandbox execution failed")
            return {
                "passed": False,
                "score": 0,
                "message": f"Sandbox error: {exc}",
                "details": {"error": True},
            }
        finally:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    logger.warning("Failed to remove container", exc_info=True)
            # Clean up temp files
            for p in (policy_path, input_path):
                p.unlink(missing_ok=True)
            Path(tmp_dir).rmdir()

    def _get_runtime(self) -> str | None:
        """Use runsc if available, fall back to default with warning."""
        info = self.client.info()
        runtimes = info.get("Runtimes", {})
        configured = self.config["RUNTIME"]
        if configured in runtimes:
            return configured
        logger.warning(
            "Runtime '%s' not available, falling back to default. Available: %s",
            configured,
            list(runtimes.keys()),
        )
        return None
