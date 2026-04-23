import asyncio

from django.test import SimpleTestCase

from gitgrit.asgi import _PathDispatcher


class TestPathDispatcher(SimpleTestCase):
    def setUp(self):
        self.mcp_calls = []
        self.django_calls = []

        async def mock_mcp(scope, receive, send):
            self.mcp_calls.append(scope.get("path", scope["type"]))

        async def mock_django(scope, receive, send):
            self.django_calls.append(scope.get("path", scope["type"]))

        self.dispatcher = _PathDispatcher(mock_mcp, mock_django)

    def _dispatch(self, scope):
        asyncio.run(self.dispatcher(scope, None, None))

    def test_mcp_path_routes_to_mcp(self):
        self._dispatch({"type": "http", "path": "/mcp/"})
        self.assertEqual(self.mcp_calls, ["/mcp/"])
        self.assertEqual(self.django_calls, [])

    def test_mcp_no_trailing_slash_routes_to_mcp(self):
        self._dispatch({"type": "http", "path": "/mcp"})
        self.assertEqual(self.mcp_calls, ["/mcp"])
        self.assertEqual(self.django_calls, [])

    def test_mcp_subpath_routes_to_mcp(self):
        self._dispatch({"type": "http", "path": "/mcp/messages/"})
        self.assertEqual(self.mcp_calls, ["/mcp/messages/"])
        self.assertEqual(self.django_calls, [])

    def test_api_path_routes_to_django(self):
        self._dispatch({"type": "http", "path": "/api/policies/"})
        self.assertEqual(self.django_calls, ["/api/policies/"])
        self.assertEqual(self.mcp_calls, [])

    def test_health_check_path_routes_to_django(self):
        self._dispatch({"type": "http", "path": "/up/"})
        self.assertEqual(self.django_calls, ["/up/"])
        self.assertEqual(self.mcp_calls, [])

    def test_root_path_routes_to_django(self):
        self._dispatch({"type": "http", "path": "/"})
        self.assertEqual(self.django_calls, ["/"])
        self.assertEqual(self.mcp_calls, [])

    def test_lifespan_routes_to_mcp(self):
        self._dispatch({"type": "lifespan"})
        self.assertEqual(self.mcp_calls, ["lifespan"])
        self.assertEqual(self.django_calls, [])

    def test_mcp_prefix_without_separator_routes_to_django(self):
        # /mcpfoo must NOT match — only /mcp and /mcp/* are MCP paths
        self._dispatch({"type": "http", "path": "/mcpfoo"})
        self.assertEqual(self.django_calls, ["/mcpfoo"])
        self.assertEqual(self.mcp_calls, [])
