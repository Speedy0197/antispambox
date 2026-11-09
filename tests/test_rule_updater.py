import importlib.util
import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch


class UpdateResults(unittest.TestCase):
    def module(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        path = root / 'files' / 'update_rules.py'
        if not path.exists():
            path = root / 'update_rules.py'
        self.assertTrue(path.exists(), 'Rule updater has not been implemented')
        spec = importlib.util.spec_from_file_location('update_rules', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_no_new_rules_is_success_without_reload(self):
        module = self.module()
        with patch.object(module, 'channels', return_value=['extra.example'], create=True), patch.object(module, 'execute', side_effect=[1, 1]):
            result = module.update()
        self.assertEqual(result['state'], 'ok')
        self.assertFalse(result['reloaded'])

    def test_partial_channel_failure_is_reported_even_when_good_rules_reload(self):
        module = self.module()
        with patch.object(module, 'channels', return_value=['extra.example'], create=True), patch.object(module, 'execute', side_effect=[0, 4, 0, 0, 0]):
            result = module.update()
        self.assertEqual(result['state'], 'partial')
        self.assertTrue(result['reloaded'])

    def test_bad_lint_prevents_reload(self):
        module = self.module()
        with patch.object(module, 'channels', return_value=['extra.example'], create=True), patch.object(module, 'execute', side_effect=[0, 1, 2]):
            result = module.update()
        self.assertEqual(result['state'], 'error')
        self.assertFalse(result['reloaded'])

    def test_current_main_feed_and_failed_extra_feed_are_partial_not_all_failed(self):
        module = self.module()
        with patch.object(module, 'channels', return_value=['extra.example'], create=True), patch.object(module, 'execute', side_effect=[1, 4]):
            result = module.update()
        self.assertEqual(result['state'], 'partial')
        self.assertFalse(result['reloaded'])

    def test_failed_reload_is_retried_even_without_another_download(self):
        module = self.module()
        with patch.object(module, 'channels', return_value=['extra.example'], create=True), patch.object(module, 'execute', side_effect=[0, 1, 0, 0, 1]):
            first = module.update()
        self.assertTrue(first.get('activation_pending', False), 'Failed activation must survive into the next run')
        with patch.object(module, 'channels', return_value=['extra.example'], create=True), patch.object(module, 'execute', side_effect=[1, 1, 0, 0, 0]):
            second = module.update(activation_pending=first['activation_pending'])
        self.assertTrue(second['reloaded'])
        self.assertFalse(second['activation_pending'])

    def test_status_write_does_not_follow_precreated_temporary_symlink(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as root:
            root = pathlib.Path(root)
            status, victim = root / 'status.json', root / 'other-file'
            victim.write_text('original')
            status.with_suffix('.new').symlink_to(victim)
            with patch.object(module, 'STATUS', status), patch.object(module, 'LOCK', root / 'lock', create=True), patch.object(module, 'update', return_value={'state': 'ok', 'activation_pending': False}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.run(), 0)
            self.assertEqual(victim.read_text(), 'original')
            self.assertFalse(status.is_symlink())
            self.assertEqual(status.stat().st_mode & 0o777, 0o600)

    def test_status_read_does_not_follow_symlinks(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as root:
            root = pathlib.Path(root)
            status, victim = root / 'status.json', root / 'other-file'
            original = json.dumps({'last_success': 'do-not-copy'})
            victim.write_text(original)
            status.symlink_to(victim)
            with patch.object(module, 'STATUS', status), patch.object(module, 'LOCK', root / 'lock', create=True), patch.object(module, 'update', return_value={'state': 'partial', 'activation_pending': False}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.run(), 1)
            self.assertEqual(victim.read_text(), original)
            self.assertNotIn('last_success', json.loads(status.read_text()))


if __name__ == '__main__':
    unittest.main()
