"""Sandbox runner — executes policy code in a gVisor-sandboxed Docker container.

Containers run on a Docker bridge network (default ``gitgrit-sandbox``,
overridable via ``SANDBOX_NETWORK``) that gives them network access while
keeping them isolated from the host machine. In air-gap deployments the
operator points this at the internal bridge that hosts the app + on-prem
GitLab so the sandbox can reach the operator's git server without internet.

DNS: gVisor's netstack can't reach Docker's embedded DNS at 127.0.0.11
(which relies on iptables DNAT), so we bind-mount a resolv.conf that
points directly to DNS servers from ``settings.SANDBOX["DNS"]``.
"""

import json
import logging
import tempfile
from pathlib import Path

import docker
from django.conf import settings

from app.domain.policy_runner import PolicyRunner

logger = logging.getLogger(__name__)

# Shared between the web container and the host so Docker bind mounts work
# when the web container creates sandbox containers via the host Docker socket.
SANDBOX_TMP = "/tmp/gitgrit-sandbox"

# In-container path where the operator-supplied CA bundle is mounted when
# settings.SANDBOX["CA_BUNDLE_HOST_PATH"] is set. The same path is exported as
# SSL_CERT_FILE inside the sandbox so policy-side TLS clients (urllib, and
# `requests` via its SSL_CERT_FILE fallback) trust the operator's CA chain.
# Keep this as the single source of truth — referenced from both the volume
# bind and the environment dict below.
CUSTOM_CA_MOUNT_PATH = "/etc/ssl/certs/custom-ca.pem"


class SandboxRunner(PolicyRunner):
    def __init__(self):
        self.client = docker.from_env()
        self.config = settings.SANDBOX
        self._ensure_network()

    def _ensure_network(self) -> None:
        """Create the sandbox bridge network if it doesn't already exist."""
        network_name = self.config["NETWORK"]
        try:
            self.client.networks.get(network_name)
        except docker.errors.NotFound:
            logger.info("Creating Docker network '%s'", network_name)
            self.client.networks.create(network_name, driver="bridge")

    def run(self, policy_code: str, input_config: dict) -> dict:
        """Run a policy script in a sandboxed container.

        Args:
            policy_code: Python source defining an evaluate(project) function.
            input_config: Dict with platform, project_id, access_token — written
                to /input.json inside the container.

        Returns:
            Policy result dict with passed, score, message, details.
        """
        Path(SANDBOX_TMP).mkdir(parents=True, exist_ok=True)
        tmp_dir = tempfile.mkdtemp(prefix="run-", dir=SANDBOX_TMP)
        policy_path = Path(tmp_dir) / "policy.py"
        input_path = Path(tmp_dir) / "input.json"
        container = None

        try:
            policy_path.write_text(policy_code)
            input_path.write_text(json.dumps(input_config))

            # gVisor can't use Docker's embedded DNS (127.0.0.11) on custom
            # networks, so we provide a resolv.conf pointing to real DNS.
            resolv_path = Path(tmp_dir) / "resolv.conf"
            resolv_path.write_text(
                "".join(f"nameserver {ns}\n" for ns in self.config["DNS"])
            )

            # LLM policies (input carries llm_roles) get higher ceilings; a
            # multi-round agentic loop won't fit the deterministic 128m/30s.
            is_llm_run = bool(input_config.get("llm_roles"))
            mem_limit = (
                self.config["LLM_MEMORY_LIMIT"]
                if is_llm_run
                else self.config["MEMORY_LIMIT"]
            )
            wait_timeout = (
                self.config["LLM_TIMEOUT"] if is_llm_run else self.config["TIMEOUT"]
            )

            runtime = self._get_runtime()
            volumes = {
                str(policy_path): {"bind": "/policy.py", "mode": "ro"},
                str(input_path): {"bind": "/input.json", "mode": "ro"},
                str(resolv_path): {"bind": "/etc/resolv.conf", "mode": "ro"},
            }
            # Air-gap only: mount the operator-supplied CA bundle and
            # propagate SSL_CERT_FILE so the sandbox's TLS clients can verify
            # an internal self-hosted GitLab. No-op for cloud (path is None).
            ca_host_path = self.config.get("CA_BUNDLE_HOST_PATH")
            sandbox_env: dict[str, str] = {}
            if ca_host_path:
                volumes[ca_host_path] = {
                    "bind": CUSTOM_CA_MOUNT_PATH,
                    "mode": "ro",
                }
                sandbox_env["SSL_CERT_FILE"] = CUSTOM_CA_MOUNT_PATH

            container_kwargs = {
                "image": self.config["IMAGE"],
                "volumes": volumes,
                "network": self.config["NETWORK"],
                "tmpfs": {"/tmp": "size=16m"},
                "mem_limit": mem_limit,
                "nano_cpus": int(self.config["CPU_LIMIT"] * 1e9),
                "cap_drop": ["ALL"],
                "detach": True,
            }

            # Only set "environment" when non-empty — cloud has historically
            # never passed an environment= kwarg, and we want byte-identical
            # container_kwargs shape in that mode.
            if sandbox_env:
                container_kwargs["environment"] = sandbox_env

            if runtime:
                container_kwargs["runtime"] = runtime

            container = self.client.containers.run(**container_kwargs)
            result = container.wait(timeout=wait_timeout)

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
            for p in (policy_path, input_path, Path(tmp_dir) / "resolv.conf"):
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
