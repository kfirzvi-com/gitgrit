"""GitLab lists a repository's files, so a project inside a GitLab monorepo
gets its own languages and root-path suggestions."""
from unittest import mock

from django.test import SimpleTestCase
from model_bakery import baker

from app.infrastructure.platform_client import GitLabClient


def _response(payload):
    resp = mock.Mock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


class GitLabTreeTests(SimpleTestCase):
    def setUp(self):
        connection = baker.prepare(
            "app.PlatformConnection", platform="gitlab", auth_method="pat",
            base_url="https://gitlab.example.test", access_token="tok",
        )
        self.client_ = GitLabClient(connection)
        patch = mock.patch("app.infrastructure.platform_client.requests.get")
        self.get = patch.start()
        self.addCleanup(patch.stop)

    def test_lists_every_file_across_pages(self):
        first = [{"path": f"apps/web/f{i}.ts", "type": "blob"} for i in range(99)] + [
            {"path": "apps/web", "type": "tree"}
        ]
        self.get.side_effect = [_response(first), _response([{"path": "go.mod", "type": "blob"}])]

        files = self.client_.get_tree("acme/platform/shop", "main")

        self.assertEqual(len(files), 100)
        self.assertNotIn("apps/web", files)
        url = self.get.call_args_list[0].args[0]
        self.assertTrue(url.endswith("/projects/acme%2Fplatform%2Fshop/repository/tree"))
        self.assertEqual(
            [c.kwargs["params"]["page"] for c in self.get.call_args_list], [1, 2]
        )
        self.assertEqual(self.get.call_args_list[0].kwargs["params"]["ref"], "main")

    def test_no_ref_reads_the_default_branch(self):
        self.get.return_value = _response([])
        self.client_.get_tree("acme/shop")
        self.assertNotIn("ref", self.get.call_args.kwargs["params"])
