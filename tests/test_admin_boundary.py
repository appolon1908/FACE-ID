"""Exercise the actual middleware body without starting app workers or devices."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    def middleware(self):
        source = Path(__file__).resolve().parents[1] / 'app/main.py'
        tree = ast.parse(source.read_text())
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == 'local_admin_boundary')
        node.decorator_list = []
        scope = {'Request': object, 'Response': lambda *args, **kwargs: SimpleNamespace(**kwargs)}
        # Imports required by the real body are executed; no application startup.
        imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
                   and any(alias.name == 'ipaddress' for alias in n.names)]
        exec(compile(ast.Module(body=imports + [node], type_ignores=[]), str(source), 'exec'), scope)
        return scope['local_admin_boundary']

    async def call(self, host, path='/v1/cameras'):
        async def next_handler(request):
            return SimpleNamespace(status_code=200)
        request = SimpleNamespace(url=SimpleNamespace(path=path), client=SimpleNamespace(host=host))
        return await self.middleware()(request, next_handler)

    async def test_public_addresses_inside_textual_172_prefix_are_denied(self):
        for host in ('172.0.0.1', '172.1.1.1', '172.15.255.255', '172.32.0.1', '172.255.1.1'):
            with self.subTest(host=host):
                self.assertEqual(403, (await self.call(host)).status_code)

    async def test_only_loopback_and_original_private_docker_range_remain_local(self):
        for host in ('127.0.0.1', '::1', 'localhost', '172.16.0.1', '172.31.255.254'):
            with self.subTest(host=host):
                self.assertEqual(200, (await self.call(host)).status_code)

    async def test_other_remote_addresses_are_denied(self):
        for host in ('203.0.113.8', '10.0.0.50', '192.168.0.1', 'malformed-host'):
            with self.subTest(host=host):
                self.assertEqual(403, (await self.call(host)).status_code)

    async def test_public_health_route_remains_available(self):
        self.assertEqual(200, (await self.call('203.0.113.8', '/healthz')).status_code)


if __name__ == '__main__':
    unittest.main()
