import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch


def load_helper():
    root = pathlib.Path(__file__).resolve().parents[1]
    path = root / 'files' / 'learning_compat.py'
    if not path.exists():
        path = root / 'learning_compat.py'
    spec = importlib.util.spec_from_file_location('learning_compat', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstalledLearner(unittest.TestCase):
    def test_flat_installation_is_located(self):
        module = load_helper()
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root) / 'irsd' / 'spamproc.py'
            path.parent.mkdir()
            path.touch()
            with patch.object(module.sys, 'path', [root, root]):
                self.assertEqual(module.installed_module(), path.resolve())

    def test_multiple_installations_are_rejected(self):
        module = load_helper()
        with tempfile.TemporaryDirectory() as root:
            for name in ('irsd/spamproc.py', 'irsd-0.0.1.egg/irsd/spamproc.py'):
                path = pathlib.Path(root) / name
                path.parent.mkdir(parents=True)
                path.touch()
            with patch.object(module.sys, 'path', [root]):
                with self.assertRaises(RuntimeError):
                    module.installed_module()


if __name__ == '__main__':
    unittest.main()
