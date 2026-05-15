"""Regression test: the sandbox runner's `containers.run` kwargs must remain
byte-identical to the pre-air-gap-changes shape when no air-gap env vars are
set. This is the safety net that protects cloud deployments from accidental
drift while the air-gap feature lives in the same codebase.

If you have a legitimate reason to change the container_kwargs shape, update
the EXPECTED constants below AND verify the change is intentional.
"""
import json
from unittest import mock

import pytest

from app.infrastructure.sandbox import runner as runner_module

EXPECTED_NETWORK = "gitgrit-sandbox"
EXPECTED_RESOLV = "nameserver 8.8.8.8\nnameserver 8.8.4.4\n"
EXPECTED_TOP_LEVEL_KEYS = {
    "image",
    "volumes",
    "network",
    "tmpfs",
    "mem_limit",
    "nano_cpus",
    "cap_drop",
    "detach",
}


def _build_runner_with_captured_kwargs():
    """Construct a SandboxRunner with the Docker client fully mocked.

    Returns (runner, captured_kwargs_list, captured_resolv_contents_list).
    """
    captured_kwargs: list[dict] = []
    captured_resolv: list[str] = []

    fake_container = mock.MagicMock()
    fake_container.wait.return_value = {"StatusCode": 0}
    fake_container.logs.side_effect = lambda stdout, stderr: (
        json.dumps(
            {"passed": True, "score": 1, "message": "ok", "details": {}}
        ).encode()
        if stdout
        else b""
    )

    def capture_run(**kwargs):
        captured_kwargs.append(kwargs)
        # Snapshot resolv.conf content because the file is cleaned up after.
        for host_path, bind in kwargs["volumes"].items():
            if bind["bind"] == "/etc/resolv.conf":
                with open(host_path) as f:
                    captured_resolv.append(f.read())
        return fake_container

    fake_client = mock.MagicMock()
    fake_client.containers.run.side_effect = capture_run
    # Default-runtime branch — we don't want to depend on runsc availability.
    fake_client.info.return_value = {"Runtimes": {}}

    with mock.patch.object(
        runner_module.docker, "from_env", return_value=fake_client
    ):
        runner = runner_module.SandboxRunner()

    return runner, captured_kwargs, captured_resolv


class TestSandboxRunnerKwargsShape:
    """With cloud defaults (no air-gap env vars), container_kwargs must equal
    the pre-change shape exactly: no `environment` key, no customer-ca mount,
    network = "gitgrit-sandbox", DNS = 8.8.8.8 + 8.8.4.4."""

    def test_cloud_kwargs_top_level_keys(self):
        runner, kwargs_list, _ = _build_runner_with_captured_kwargs()
        runner.run("def evaluate(p): return {}", {"platform": "github"})
        assert len(kwargs_list) == 1
        kwargs = kwargs_list[0]
        assert set(kwargs.keys()) == EXPECTED_TOP_LEVEL_KEYS, (
            "container_kwargs has unexpected keys for cloud defaults. "
            "An air-gap-only key (likely 'environment') leaked into the "
            "cloud path. Diff: "
            f"{set(kwargs.keys()) ^ EXPECTED_TOP_LEVEL_KEYS}"
        )

    def test_cloud_kwargs_no_environment_key(self):
        runner, kwargs_list, _ = _build_runner_with_captured_kwargs()
        runner.run("def evaluate(p): return {}", {"platform": "github"})
        assert "environment" not in kwargs_list[0]

    def test_cloud_kwargs_network_default(self):
        runner, kwargs_list, _ = _build_runner_with_captured_kwargs()
        runner.run("def evaluate(p): return {}", {"platform": "github"})
        assert kwargs_list[0]["network"] == EXPECTED_NETWORK

    def test_cloud_kwargs_no_customer_ca_mount(self):
        runner, kwargs_list, _ = _build_runner_with_captured_kwargs()
        runner.run("def evaluate(p): return {}", {"platform": "github"})
        binds = [v["bind"] for v in kwargs_list[0]["volumes"].values()]
        assert "/etc/ssl/certs/customer-ca.pem" not in binds
        # Volumes should be exactly the three legacy mounts.
        assert sorted(binds) == sorted(
            ["/policy.py", "/input.json", "/etc/resolv.conf"]
        )

    def test_cloud_resolv_conf_bytes_identical(self):
        runner, _, resolv_list = _build_runner_with_captured_kwargs()
        runner.run("def evaluate(p): return {}", {"platform": "github"})
        assert resolv_list == [EXPECTED_RESOLV]


class TestSandboxRunnerAirgapBehavior:
    """With air-gap env vars set, the runner must add the env propagation and
    the CA mount. This is the positive side of the regression test."""

    def test_airgap_adds_environment_and_ca_mount(self, settings, tmp_path):
        ca_path = tmp_path / "ca.pem"
        ca_path.write_text("-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n")
        settings.SANDBOX = {
            **settings.SANDBOX,
            "CA_BUNDLE_HOST_PATH": str(ca_path),
            "SANDBOX_ENV": {"SSL_CERT_FILE": "/etc/ssl/certs/customer-ca.pem"},
            "NETWORK": "gitgrit_internal",
            "DNS": ["10.0.0.53"],
        }

        runner, kwargs_list, resolv_list = _build_runner_with_captured_kwargs()
        runner.run("def evaluate(p): return {}", {"platform": "gitlab"})

        kwargs = kwargs_list[0]
        assert kwargs["environment"] == {
            "SSL_CERT_FILE": "/etc/ssl/certs/customer-ca.pem"
        }
        assert kwargs["network"] == "gitgrit_internal"
        binds = {v["bind"] for v in kwargs["volumes"].values()}
        assert "/etc/ssl/certs/customer-ca.pem" in binds
        # And the host-side mount key should be the operator-supplied path.
        assert str(ca_path) in kwargs["volumes"]
        assert kwargs["volumes"][str(ca_path)]["mode"] == "ro"
        assert resolv_list == ["nameserver 10.0.0.53\n"]
