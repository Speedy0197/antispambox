"""Validate the real system-cron file, including Debian cron acceptance rules."""
import pathlib
import pwd
import unittest


class SystemCron(unittest.TestCase):
    def setUp(self):
        if not pathlib.Path('/etc/cron.d/antispambox-rules').exists():
            self.skipTest('Cron integration checks require the built container')

    def test_file_is_not_group_or_world_writable(self):
        path = pathlib.Path('/etc/cron.d/antispambox-rules')
        self.assertEqual(path.stat().st_mode & 0o022, 0)

    def test_jobs_have_a_real_system_username_and_existing_command(self):
        jobs = [l.split() for l in pathlib.Path('/etc/cron.d/antispambox-rules').read_text().splitlines()
                if l.strip() and not l.lstrip().startswith('#') and '=' not in l.split()[0]]
        self.assertTrue(jobs, 'The explicit daily update schedule must exist')
        for fields in jobs:
            self.assertGreaterEqual(len(fields), 7)
            try:
                pwd.getpwnam(fields[5])
            except KeyError:
                self.fail('System cron job has no valid username field')
            self.assertTrue(pathlib.Path(fields[6]).is_file())


if __name__ == '__main__':
    unittest.main()
