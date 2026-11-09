import importlib.util
import json
import os
import pathlib
import pwd
import sys
import tempfile
import unittest
from unittest.mock import patch


def startup():
    root = pathlib.Path(__file__).resolve().parents[1]
    folder = root / 'files'
    if not folder.exists():
        folder = root
    spec = importlib.util.spec_from_file_location('startup', folder / 'startup.py')
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, 'path', [str(folder)] + sys.path):
        spec.loader.exec_module(module)
    return module


class AccountConfiguration(unittest.TestCase):
    def enabled(self, config):
        module = startup()
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root) / 'account.json'
            path.write_text(json.dumps(config))
            return module.account_enabled(path)

    def test_disabled_account_does_not_start_scanning(self):
        self.assertFalse(self.enabled({'antispambox': {'enabled': 'False', 'account': {}}}))

    def test_explicit_enabled_configuration_is_accepted(self):
        self.assertTrue(self.enabled({'antispambox': {'enabled': True, 'account': {
            'server': 'mail.example.invalid', 'user': 'example', 'password': 'test-placeholder'}}}))

    def test_placeholder_server_is_not_a_configured_account(self):
        self.assertFalse(self.enabled({'antispambox': {'enabled': 'True', 'account': {
            'server': 'imap.example.net', 'user': 'example', 'password': 'test-placeholder'}}}))

    def test_incomplete_configuration_is_disabled(self):
        self.assertFalse(self.enabled({'antispambox': {'enabled': True, 'account': {'server': 'mail.example.invalid'}}}))


class ClassifierPermissions(unittest.TestCase):
    def setUp(self):
        if os.geteuid() != 0:
            self.skipTest('Ownership checks require the built image')
        try:
            pwd.getpwnam('debian-spamd')
            pwd.getpwnam('redis')
        except KeyError:
            self.skipTest('Daemon accounts require the built image')

    def test_known_data_is_retained_without_world_write(self):
        module = startup()
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root) / 'bayesdb'
            path.mkdir()
            (path / 'bayes_toks').write_bytes(b'classifier-placeholder')
            (path / 'dump.rdb').write_bytes(b'redis-placeholder')
            (path / 'rule-update-status.json').write_text('{}')
            (path / 'rule-update-status.json').chmod(0o600)
            module.prepare_data(path)
            self.assertEqual((path / 'bayes_toks').read_bytes(), b'classifier-placeholder')
            self.assertEqual((path / 'dump.rdb').read_bytes(), b'redis-placeholder')
            self.assertEqual(path.stat().st_mode & 0o007, 0)
            self.assertEqual((path / 'dump.rdb').stat().st_uid, pwd.getpwnam('redis').pw_uid)
            self.assertEqual((path / 'rule-update-status.json').stat().st_mode & 0o777, 0o600)

    def test_classifier_symlinks_are_rejected(self):
        module = startup()
        with tempfile.TemporaryDirectory() as root:
            root = pathlib.Path(root)
            path = root / 'bayesdb'
            path.mkdir()
            victim = root / 'other-file'
            victim.write_bytes(b'unchanged')
            (path / 'bayes_toks').symlink_to(victim)
            with self.assertRaises(RuntimeError):
                module.prepare_data(path)
            self.assertEqual(victim.read_bytes(), b'unchanged')


if __name__ == '__main__':
    unittest.main()
