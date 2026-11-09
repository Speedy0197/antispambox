"""Regression checks against the actual installed IRSD learn_mail function."""
import ast
import importlib.util
import pathlib
import types
import unittest


class TrainingResults(unittest.TestCase):
    def result(self, exitcode):
        root = pathlib.Path(__file__).resolve().parents[1]
        helper = root / 'files' / 'learning_compat.py'
        if not helper.exists():
            helper = root / 'learning_compat.py'
        spec = importlib.util.spec_from_file_location('learning_compat', helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            path = module.installed_module()
        except RuntimeError:
            self.skipTest('IRSD integration checks require the built container')
        tree = ast.parse(path.read_text())
        function = next(n for n in tree.body
                        if isinstance(n, ast.FunctionDef) and n.name == 'learn_mail')
        class Process:
            returncode = exitcode
            stdin = types.SimpleNamespace(close=lambda: None)
            def communicate(self, payload):
                return b'', b''
        namespace = {
            'utils': types.SimpleNamespace(popen=lambda command: Process()),
            'imaputils': types.SimpleNamespace(mail_content=lambda mail: b'test'),
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
        return namespace['learn_mail'](object(), 'spam')

    def test_success_is_learned(self):
        self.assertEqual(self.result(0), (5, 5))

    def test_connection_failure_is_retryable_not_already_learned(self):
        self.assertEqual(self.result(1), (-9999, 1))

    def test_other_command_failure_is_retryable(self):
        self.assertEqual(self.result(2), (-9999, 2))



class ClientEntrypoints(unittest.TestCase):
    def check(self, name):
        import shutil
        import subprocess
        executable = shutil.which(name)
        if not executable:
            self.skipTest('Client entrypoint requires the built image')
        result = subprocess.run([executable, '--help'], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, 'Installed client cannot start on this Python version')

    def test_isbg_entrypoint_imports(self):
        self.check('isbg')

    def test_irsd_entrypoint_imports(self):
        self.check('irsd')

if __name__ == '__main__':
    unittest.main()
