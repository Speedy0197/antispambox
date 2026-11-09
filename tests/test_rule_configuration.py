import shutil
import subprocess
import unittest


class RuleConfiguration(unittest.TestCase):
    @unittest.skipUnless(shutil.which('spamassassin'), 'Rule validation requires the built container')
    def test_installed_rules_pass_native_validation(self):
        result = subprocess.run(['spamassassin', '--lint'], capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, 'Installed rules failed native validation')


if __name__ == '__main__':
    unittest.main()
