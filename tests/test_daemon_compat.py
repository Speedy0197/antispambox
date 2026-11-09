import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch


def updater():
    root = pathlib.Path(__file__).resolve().parents[1]
    path = root / 'files' / 'update_rules.py'
    if not path.exists():
        path = root / 'update_rules.py'
    spec = importlib.util.spec_from_file_location('update_rules', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DaemonCompatibility(unittest.TestCase):
    def disable(self, module, path):
        function = getattr(module, 'disable_daily_updates', None)
        self.assertTrue(callable(function), 'Modern daemon defaults are not supported')
        return function(path)

    def test_modern_defaults_without_cron_toggle_are_supported(self):
        module = updater()
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root) / 'spamd'
            path.write_text('OPTIONS="--allow-tell"\n')
            self.assertTrue(self.disable(module, path))
            self.assertIn('OPTIONS="--allow-tell"', path.read_text())
            self.assertEqual(path.read_text().splitlines().count('CRON=0'), 1)

    def test_existing_daily_toggle_is_disabled(self):
        module = updater()
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root) / 'spamassassin'
            path.write_text('CRON=1\nOPTIONS="--allow-tell"\n')
            self.disable(module, path)
            self.assertNotIn('CRON=1', path.read_text())
            self.assertIn('CRON=0', path.read_text())

    def test_missing_legacy_defaults_are_not_created(self):
        module = updater()
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root) / 'missing'
            self.assertFalse(self.disable(module, path))
            self.assertFalse(path.exists())

    def test_modern_daemon_service_name_is_selected(self):
        module = updater()
        function = getattr(module, 'spamd_service_name', None)
        self.assertTrue(callable(function), 'Modern spamd service is not supported')
        with patch.object(module.pathlib.Path, 'is_file', return_value=True):
            self.assertEqual(function(), 'spamd')


if __name__ == '__main__':
    unittest.main()
