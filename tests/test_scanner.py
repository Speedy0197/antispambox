import ast
import pathlib
import types
import unittest


class ScannerArguments(unittest.TestCase):
    def test_password_is_one_argument_without_shell_interpretation(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        path = root / 'files' / 'antispambox.py'
        if not path.exists():
            path = root / 'antispambox.py'
        tree = ast.parse(path.read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'scan_spam')
        calls = []
        def popen(command, **kwargs):
            calls.append((command, kwargs))
            return types.SimpleNamespace(returncode=0, communicate=lambda: (b'', b''))
        secret = 'test-placeholder $() ; with spaces'
        namespace = dict(HOST='mail.example.invalid', USERNAME='example', PASSWORD=secret,
                         JUNK='Junk', INPUT='INBOX', HAMTRAIN='Ham', SPAMTRAIN='TrainSpam',
                         SPAMTRAIN2='TrainSpam', CACHEPATH='rspamd',
                         subprocess=types.SimpleNamespace(Popen=popen, PIPE=-1),
                         logger=types.SimpleNamespace(info=lambda *args: None, warning=lambda *args: None))
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
        namespace['scan_spam']()
        self.assertEqual(len(calls), 2)
        for command, options in calls:
            self.assertIn(secret, command)
            self.assertFalse(options.get('shell', False))
            self.assertEqual(command[command.index('--imappasswd') + 1], secret)


if __name__ == '__main__':
    unittest.main()
