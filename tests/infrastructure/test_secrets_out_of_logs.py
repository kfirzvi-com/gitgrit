"""Accidental echoes of secrets are replaced in logs and stored results
(SOC 2 CC6.1, C1.1).

The sandbox input carries the repository access token and the workspace's
LLM API keys, and the LLM provider calls hold a key. A standard's code, a
provider or library error, or Docker itself can echo them; whatever we log
(CloudWatch, kept a year), store (StandardExecution, Project.deps_error) or
publish has them replaced. The first-run setup token is never logged or put
in a URL, and the invitation page doesn't spread its token further.
"""
import io
import json
import logging
import time
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings, tag
from model_bakery import baker

from app import tasks
from app.application import event_bus, subscribers
from app.application.standard_engine import StandardEngine
from app.domain.events import DependencyInferenceFailed
from app.domain.limits import MAX_ERROR_TEXT
from app.domain.models import AuthMethod, Project, StandardExecution, WorkspaceInvitation
from app.infrastructure import github_app, llm_models
from app.infrastructure.redaction import REDACTED, redact, redacted_failure, secrets_in
from app.infrastructure.sandbox import runner as runner_module
from tests.support import MonkeyPatchMixin, NoPlatformLookupsMixin

TOKEN = "ghs_fakeAccessToken0123456789abcdef"
API_KEY = "sk-ant-fake-key-9876543210zyxwvu"
INPUT = {
    "platform": "github",
    "project_id": "42",
    "access_token": TOKEN,
    "llm_roles": {"decision": {"model": "anthropic/x", "base_url": "", "api_key": API_KEY}},
}


def _runner(stdout=b"", stderr=b"", exit_code=0, run_error=None):
    container = mock.MagicMock()
    container.wait.return_value = {"StatusCode": exit_code}
    container.logs.side_effect = lambda **kw: stdout if kw.get("stdout") else stderr
    client = mock.MagicMock()
    client.info.return_value = {"Runtimes": {}}
    if run_error:
        client.containers.run.side_effect = run_error
    else:
        client.containers.run.return_value = container
    with mock.patch.object(runner_module.docker, "from_env", return_value=client):
        return runner_module.SandboxRunner()


def _stderr_levels(records):
    # Building the runner also logs (the runsc check); only stderr lines count.
    return [r.levelname for r in records if "stderr" in r.getMessage()]


def _all_text(records):
    return "\n".join(r.getMessage() for r in records)


@tag("security")
class RedactionTests(SimpleTestCase):
    def test_collects_the_token_and_every_llm_key(self):
        assert secrets_in(INPUT) == {TOKEN, API_KEY}

    def test_ignores_empty_and_short_values(self):
        assert secrets_in({"access_token": None, "llm_roles": {"r": {"api_key": "abc"}}}) == set()
        # A provider with no key must not blank out every character.
        assert redact("plain text", {"", None, "abc"}) == "plain text"

    def test_replaces_secrets_anywhere_in_nested_results(self):
        result = {
            "message": f"auth failed for {TOKEN}",
            "details": {"logs": [f"key={API_KEY}", 3, None], "ok": True},
        }
        clean = redact(result, {TOKEN, API_KEY})
        assert TOKEN not in json.dumps(clean) and API_KEY not in json.dumps(clean)
        assert clean["message"] == f"auth failed for {REDACTED}"
        assert clean["details"]["logs"] == [f"key={REDACTED}", 3, None]
        assert clean["details"]["ok"] is True

    def test_a_truncated_long_secret_is_caught(self):
        clean = redact(f"invalid key {API_KEY[:20]}...", {API_KEY})
        assert API_KEY[:12] not in clean
        assert clean.startswith(f"invalid key {REDACTED}")

    def test_the_whole_secret_is_replaced_not_just_its_prefix(self):
        assert redact(f"<{API_KEY}>", {API_KEY}) == f"<{REDACTED}>"

    def test_dict_keys_are_redacted_too(self):
        clean = redact({"files": {f"https://{TOKEN}@github.com": 1, 2: "x"}}, {TOKEN})
        assert clean == {"files": {f"https://{REDACTED}@github.com": 1, 2: "x"}}


@tag("security")
class ReraiseRedactedTests(SimpleTestCase):
    def _reraise(self, exc):
        try:
            raise exc
        except type(exc) as caught:
            message, stack = redacted_failure(caught, {TOKEN})
            tasks._reraise_redacted(caught, message, stack)

    def test_a_secret_past_the_stored_cut_is_still_caught(self):
        text = "x" * (MAX_ERROR_TEXT + 100) + TOKEN
        with self.assertRaises(RuntimeError) as raised:
            self._reraise(ValueError(text))
        assert TOKEN not in str(raised.exception)
        assert raised.exception.__cause__ is None and raised.exception.__suppress_context__

    def test_a_secret_in_the_cause_is_caught(self):
        # The top message is clean, but the worker would log the whole chain.
        try:
            try:
                raise ValueError(f"clone failed with {TOKEN}")
            except ValueError as cause:
                raise KeyError("missing") from cause
        except KeyError as caught:
            error = caught
        with self.assertRaises(RuntimeError) as raised:
            self._reraise(error)
        assert raised.exception is not error
        assert raised.exception.__cause__ is None and raised.exception.__suppress_context__
        assert TOKEN not in str(raised.exception)

    def test_an_error_without_secrets_keeps_its_type(self):
        error = KeyError("missing")
        with self.assertRaises(KeyError) as raised:
            self._reraise(error)
        assert raised.exception is error


@tag("security")
class InputConfigContractTests(TestCase):
    """``secrets_in`` reads the keys ``build_input_config`` writes."""

    def test_finds_the_token_and_every_role_key_of_a_real_input(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make(
            "app.PlatformConnection", tenant=tenant, platform="github", access_token=TOKEN
        )
        project = baker.make("app.Project", tenant=tenant, platform_connection=conn)
        other_key = "sk-openai-fake-1234567890abcdef"
        for name, key in (("reasoning", API_KEY), ("code", other_key)):
            provider = baker.make("app.LLMProvider", tenant=tenant, api_key=key, enabled=True)
            baker.make("app.LLMRole", tenant=tenant, name=name, provider=provider, model="m")

        cfg = StandardEngine().build_input_config(project)

        assert secrets_in(cfg) == {TOKEN, API_KEY, other_key}


@tag("security")
class SandboxRunnerRedactionTests(SimpleTestCase):
    def test_stored_result_has_no_secrets(self):
        out = json.dumps({
            "passed": False, "score": 0, "message": f"token {TOKEN}",
            "details": {"logs": [f"calling LLM with {API_KEY}"]},
        }).encode()
        result = _runner(stdout=out).run("code", INPUT)
        assert TOKEN not in json.dumps(result)
        assert API_KEY not in json.dumps(result)
        assert REDACTED in result["message"]

    def test_stderr_is_logged_once_without_secrets(self):
        out = json.dumps({"passed": True, "score": 100, "message": "", "details": {}}).encode()
        err = f"Traceback: Authorization: Bearer {TOKEN} api_key={API_KEY}".encode()
        with self.assertLogs(runner_module.logger, "WARNING") as logs:
            _runner(stdout=out, stderr=err, exit_code=1).run("code", INPUT)
        text = _all_text(logs.records)
        assert REDACTED in text
        assert TOKEN not in text and API_KEY not in text
        assert _stderr_levels(logs.records) == ["ERROR"]
        assert "exited with code 1" in text

    def test_stderr_of_a_clean_exit_is_a_warning(self):
        out = json.dumps({"passed": True, "score": 100, "message": "", "details": {}}).encode()
        with self.assertLogs(runner_module.logger, "WARNING") as logs:
            _runner(stdout=out, stderr=b"a deprecation note").run("code", INPUT)
        assert _stderr_levels(logs.records) == ["WARNING"]

    def test_unparsable_output_is_logged_without_secrets(self):
        with self.assertLogs(runner_module.logger, "ERROR") as logs:
            _runner(stdout=f"not json {TOKEN}".encode()).run("code", INPUT)
        assert TOKEN not in _all_text(logs.records)

    def test_docker_error_is_logged_with_a_redacted_stack(self):
        error = RuntimeError(f"pull failed: https://x-access-token:{TOKEN}@github.com")
        with self.assertLogs(runner_module.logger, "ERROR") as logs:
            result = _runner(run_error=error).run("code", INPUT)
        assert TOKEN not in result["message"]
        text = _all_text(logs.records)
        assert "Traceback" in text and REDACTED in text
        assert TOKEN not in text
        # The raw exception isn't attached for a handler to format.
        assert all(r.exc_info is None for r in logs.records)


@tag("security")
class LLMProviderErrorRedactionTests(SimpleTestCase):
    def test_probe_detail_has_no_key(self):
        error = Exception(f'{{"error": {{"code": 401, "message": "bad key {API_KEY[:20]}"}}}}')
        with mock.patch("litellm.completion", side_effect=error):
            result = llm_models._probe_model("anthropic", "", API_KEY, "m", 1.0)
        assert API_KEY[:12] not in result.detail
        assert REDACTED in result.detail

    def test_discovery_failure_is_logged_without_the_key(self):
        error = RuntimeError(f"GET https://x/models?key={API_KEY} failed")
        with mock.patch.object(llm_models, "fetch_catalog", side_effect=error), \
                self.assertLogs(llm_models.logger, "WARNING") as logs:
            assert llm_models.discover("gemini", "", API_KEY).models == []
        assert API_KEY not in _all_text(logs.records)

    def test_provider_test_failure_is_logged_without_the_key(self):
        error = RuntimeError(f"401 for key {API_KEY}")
        with mock.patch.object(llm_models, "fetch_catalog", side_effect=error), \
                self.assertLogs(llm_models.logger, "INFO") as logs:
            assert llm_models.test_provider("openai", "", API_KEY) is False
        text = _all_text(logs.records)
        assert API_KEY not in text and REDACTED in text


@tag("security")
class DependencyMapErrorRedactionTests(MonkeyPatchMixin, TestCase):
    def setUp(self):
        super().setUp()
        event_bus.clear()
        self.addCleanup(subscribers.register)
        self.addCleanup(event_bus.clear)
        self.events = []
        event_bus.subscribe(DependencyInferenceFailed, self.events.append)
        self.monkeypatch.setattr(tasks, "_sleep", lambda seconds: None)

    def test_provider_error_is_redacted_everywhere(self):
        tenant = baker.make("app.Tenant")
        provider = baker.make("app.LLMProvider", tenant=tenant, api_key=API_KEY, enabled=True)
        baker.make("app.LLMRole", tenant=tenant, name="reasoning", provider=provider, model="m")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        project = baker.make("app.Project", tenant=tenant, platform_connection=conn)

        def fail(project):
            raise RuntimeError(f"AuthenticationError: invalid x-api-key {API_KEY}")

        self.monkeypatch.setattr("app.application.dependency_agent.infer_and_store", fail)

        with self.assertLogs(tasks.logger, "ERROR") as logs, \
                self.assertRaises(RuntimeError) as raised:
            tasks.infer_project_dependencies.func(project_id=str(project.id))

        project.refresh_from_db()
        assert API_KEY not in project.deps_error and REDACTED in project.deps_error
        assert API_KEY not in self.events[0].error
        assert API_KEY not in str(raised.exception)
        assert raised.exception.__cause__ is None and raised.exception.__suppress_context__
        text = _all_text(logs.records)
        assert API_KEY not in text and "Traceback" in text
        assert all(r.exc_info is None for r in logs.records)


@tag("security")
class RunStandardsErrorRedactionTests(NoPlatformLookupsMixin, TestCase):
    def test_job_failure_is_redacted_in_the_rows_and_the_log(self):
        tenant = baker.make("app.Tenant")
        project = baker.make("app.Project", tenant=tenant)
        standard = baker.make("app.Standard", tenant=tenant, code="x")
        execution = baker.make(
            "app.StandardExecution", project=project, standard=standard,
            standard_name=standard.name, event_type="manual",
            status=StandardExecution.Status.RUNNING,
        )
        boom = RuntimeError(f"clone failed with {TOKEN}")
        with mock.patch.object(StandardEngine, "build_input_config", return_value=INPUT), \
                mock.patch.object(StandardEngine, "run_execution", side_effect=boom), \
                self.assertLogs(tasks.logger, "ERROR") as logs, \
                self.assertRaises(RuntimeError) as raised:
            tasks.run_standards.func(project_id=str(project.id), execution_ids=[str(execution.id)])

        execution.refresh_from_db()
        assert execution.status == StandardExecution.Status.ERROR
        assert TOKEN not in execution.message and REDACTED in execution.message
        assert TOKEN not in json.dumps(execution.details)
        assert TOKEN not in str(raised.exception)
        assert TOKEN not in _all_text(logs.records)


@tag("security")
@override_settings(FIRST_RUN_SETUP_ENABLED=True)
class SetupTokenNotLoggedTests(TestCase):
    def test_setup_hint_names_the_command_not_the_token(self):
        from app.application.access import setup_token

        with self.assertLogs("app.access", "WARNING") as logs:
            response = self.client.get("/dashboard/")
        assert response.status_code == 302
        text = _all_text(logs.records)
        assert setup_token() not in text
        assert "manage.py setup_token" in text
        assert "?token=" not in text


@tag("security")
class InvitationPageTests(TestCase):
    def test_page_sends_no_referrer_and_logs_no_token(self):
        owner = baker.make("app.User", email="olga@acme.example")
        tenant = baker.make("app.Tenant", name="Acme")
        invitation, token = WorkspaceInvitation.issue(tenant, "new@acme.example", "member", owner)
        invitation.save()

        with self.assertLogs(level="DEBUG") as logs:
            logging.getLogger("app").debug("start")  # assertLogs needs one record
            response = self.client.get(f"/invitations/{token}/")

        assert response.status_code == 200
        assert response["Referrer-Policy"] == "no-referrer"
        assert "no-store" in response["Cache-Control"]
        assert token not in _all_text(logs.records)


@tag("security")
class GitHubAppTokenRedactionTests(MonkeyPatchMixin, TestCase):
    """An App connection mints a short-lived installation token per job; it
    is stored nowhere but the process's installation token cache, which the
    failure path reads (github_app.cached_tokens)."""

    MINTED = "ghs_mintedInstallationToken0123456789"

    def setUp(self):
        super().setUp()
        self.monkeypatch.setattr(tasks, "_sleep", lambda seconds: None)
        # The real cache, minting mocked at GitHub's API.
        github_app.clear_token_cache()
        self.addCleanup(github_app.clear_token_cache)
        response = mock.Mock()
        response.json.return_value = {
            "token": self.MINTED,
            "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600)),
        }
        self.monkeypatch.setattr(github_app, "build_app_jwt", lambda: "fake.jwt")
        self.monkeypatch.setattr(github_app.requests, "post", lambda *a, **kw: response)
        tenant = baker.make("app.Tenant")
        conn = baker.make(
            "app.PlatformConnection", tenant=tenant, platform="github",
            auth_method=AuthMethod.GITHUB_APP, installation_id=123, access_token=None,
        )
        self.project = baker.make("app.Project", tenant=tenant, platform_connection=conn)

    def test_dependency_map_failure_hides_the_minted_token(self):
        class Inference:
            def infer(self, snapshot, context):
                raise RuntimeError(f"401 reading tree with {snapshot._client.token}")

        self.monkeypatch.setattr(
            "app.application.dependency_agent.llm_inference_for", lambda tenant: Inference()
        )
        self.monkeypatch.setattr(
            "app.infrastructure.topology.snapshots.get_platform_client",
            lambda connection: mock.Mock(),
        )
        with self.assertLogs(tasks.logger, "ERROR") as logs, \
                self.assertRaises(RuntimeError) as raised:
            tasks.infer_project_dependencies.func(project_id=str(self.project.id))

        self.project.refresh_from_db()
        assert "401 reading tree" in self.project.deps_error
        assert self.MINTED not in self.project.deps_error
        assert self.MINTED not in str(raised.exception)
        assert self.MINTED not in _all_text(logs.records)

    def test_run_standards_failure_hides_the_minted_token(self):
        standard = baker.make("app.Standard", tenant=self.project.tenant, code="x")
        execution = baker.make(
            "app.StandardExecution", project=self.project, standard=standard,
            standard_name=standard.name, event_type="manual",
            status=StandardExecution.Status.RUNNING,
        )
        def pin(project, executions):
            # Mints (as the platform client does), then fails before the
            # input is built: only the installation token cache has it.
            token = project.platform_connection.get_access_token()
            raise RuntimeError(f"listing commits failed with {token}")

        with mock.patch("app.application.commit_checks.pin_head_commits", side_effect=pin), \
                self.assertLogs(tasks.logger, "ERROR") as logs, \
                self.assertRaises(RuntimeError) as raised:
            tasks.run_standards.func(
                project_id=str(self.project.id), execution_ids=[str(execution.id)]
            )

        execution.refresh_from_db()
        assert REDACTED in execution.message and self.MINTED not in execution.message
        assert self.MINTED not in str(raised.exception)
        assert self.MINTED not in _all_text(logs.records)

    def test_a_token_minted_through_another_instance_is_hidden(self):
        # Minted by a separately fetched copy of the connection: the failure
        # path's project never touched it.
        other = Project.objects.select_related("platform_connection").get(pk=self.project.pk)
        token = other.platform_connection.get_access_token()

        def fail(project):
            raise RuntimeError(f"401 with {token}")

        self.monkeypatch.setattr("app.application.dependency_agent.infer_and_store", fail)
        with self.assertLogs(tasks.logger, "ERROR") as logs, self.assertRaises(RuntimeError):
            tasks.infer_project_dependencies.func(project_id=str(self.project.id))

        self.project.refresh_from_db()
        assert self.MINTED not in self.project.deps_error
        assert REDACTED in self.project.deps_error
        assert self.MINTED not in _all_text(logs.records)


@tag("security")
class RefreshProjectDepsCommandRedactionTests(MonkeyPatchMixin, TestCase):
    def test_sync_failure_hides_the_token_and_the_llm_key(self):
        tenant = baker.make("app.Tenant")
        provider = baker.make("app.LLMProvider", tenant=tenant, api_key=API_KEY, enabled=True)
        baker.make("app.LLMRole", tenant=tenant, name="reasoning", provider=provider, model="m")
        conn = baker.make(
            "app.PlatformConnection", tenant=tenant, platform="github", access_token=TOKEN
        )
        project = baker.make("app.Project", tenant=tenant, platform_connection=conn)

        def fail(project):
            raise RuntimeError(f"inference failed: token={TOKEN} key={API_KEY}")

        self.monkeypatch.setattr("app.application.dependency_agent.infer_and_store", fail)
        stdout, stderr = io.StringIO(), io.StringIO()
        call_command("refresh_project_deps", str(project.id), "--sync", stdout=stdout, stderr=stderr)

        project.refresh_from_db()
        assert project.deps_status == Project.DepsStatus.FAILED
        assert "inference failed" in project.deps_error and REDACTED in project.deps_error
        for text in (project.deps_error, stderr.getvalue(), stdout.getvalue()):
            assert TOKEN not in text and API_KEY not in text
