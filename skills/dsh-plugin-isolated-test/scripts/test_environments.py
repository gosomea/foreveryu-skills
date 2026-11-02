"""Behavior checks using disposable databases and injected process observations."""
import concurrent.futures
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from environments import Registry, check, origin


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.filename = self.root / 'registry.sqlite3'
        self.registry = Registry(self.filename)
        self.data = dict(source=str(self.root), plugin=str(self.root), profile='test',
                         purpose='中文任务', state='active')

    def tearDown(self):
        self.registry.close()
        self.temp.cleanup()

    def register(self, ident='first', home=None, **options):
        return self.registry.register(ident, str(self.root), home or str(self.root / ident),
                                      self.data, **options)

    def test_reopen_keeps_project_case_and_session(self):
        self.register(preferred=True)
        self.registry.bind('first', 'smoke', str(self.root), '验证中文批准', 'session-1')
        other = Registry(self.filename)
        try:
            records = other.list(str(self.root / '.'))
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]['preferred'])
            self.assertEqual(records[0]['cases'][0]['session_id'], 'session-1')
            self.assertEqual(records[0]['purpose'], '中文任务')
        finally:
            other.close()
        self.assertEqual(self.filename.stat().st_mode & 0o777, 0o600)

    def test_new_environment_requires_reason_and_preference_is_unique(self):
        self.register(preferred=True)
        with self.assertRaises(ValueError):
            self.register('second')
        self.register('second', preferred=True, reason='并行测试不同构建')
        self.assertFalse(self.registry.get('first')['preferred'])
        self.assertTrue(self.registry.get('second')['preferred'])
        self.registry.update('second', {'state': 'retired'})
        self.assertFalse(self.registry.get('second')['preferred'])

    def test_same_home_cannot_gain_second_identity_and_rolls_back(self):
        self.register(preferred=True)
        with self.assertRaises(Exception):
            self.register('alias', home=str(self.root / 'first'), preferred=True, reason='duplicate')
        self.assertTrue(self.registry.get('first')['preferred'])
        self.assertEqual(len(self.registry.list()), 1)

    def test_two_sessions_cannot_silently_register_parallel_environments(self):
        def add(number):
            registry = Registry(self.filename)
            try:
                registry.register(str(number), str(self.root), str(self.root / str(number)), self.data)
                return True
            except ValueError:
                return False
            finally:
                registry.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(add, range(2))), [False, True])

    def test_pid_reuse_and_missing_workspace_are_not_healthy(self):
        record = self.register()
        record.update(pid=123, process_fingerprint='original', url='http://127.0.0.1:1')
        record['cases'] = [{'id': 'old', 'workspace': str(self.root / 'gone')}]
        with patch('environments.fingerprint', return_value='different'):
            result = check(record)
        self.assertEqual(result['process'], 'identity-changed')
        self.assertFalse(result['live_identity_verified'])
        self.assertEqual(result['missing_case_workspaces'], ['old'])

    def test_listener_alone_does_not_prove_identity(self):
        record = self.register(home=str(self.root))
        record.update(pid=123, process_fingerprint='original', url='http://127.0.0.1:12345')
        def fake_run(*args):
            if args[0] == 'ps' and 'eww' in args:
                return f'node DSH_HOME={self.root / "wrong"} SECRET=hidden'
            if args[0] == 'ps':
                return 'node --profile test'
            if '-d' in args:
                return f'p123\nfcwd\nn{self.root}'
            return '123'
        with patch('environments.fingerprint', return_value='original'), \
             patch('environments.shutil.which', return_value='/usr/bin/lsof'), \
             patch('environments.run', side_effect=fake_run):
            result = check(record)
        self.assertEqual(result['listener'], 'matches')
        self.assertEqual(result['home'], 'mismatch')
        self.assertFalse(result['live_identity_verified'])
        self.assertNotIn('hidden', str(result))

    def test_auth_links_are_not_registry_urls(self):
        self.assertEqual(origin('http://127.0.0.1:31973/'), 'http://127.0.0.1:31973')
        for invalid in ('http://127.0.0.1:31973/?token=secret', 'http://user:pass@localhost:80',
                        'https://example.com:443', 'http://localhost:80/path'):
            with self.assertRaises(ValueError):
                origin(invalid)


if __name__ == '__main__':
    unittest.main()
