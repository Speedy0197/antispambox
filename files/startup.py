"""Start the local filter daemons and preserve the existing account/data volumes."""
import argparse
import grp
import json
import logging
import os
import pathlib
import pwd
import re
import signal
import subprocess
import sys
import threading
import time

import healthcheck
import learning_compat
import update_rules

LOGGER = logging.getLogger('antispambox.startup')
STOP = threading.Event()
DATA = pathlib.Path('/var/spamassassin/bayesdb')
ACCOUNT = pathlib.Path('/root/accounts/imap_accounts.json')
SPAMD_ARGS = ['/usr/sbin/spamd', '--allow-tell', '--max-children', '5',
              '--helper-home-dir', '-u', 'debian-spamd', '-x',
              '--virtual-config-dir=/var/spamassassin', '--listen=127.0.0.1',
              '--port=783', '--syslog=stderr']


def account_enabled(path=ACCOUNT):
    try:
        config = json.loads(path.read_text())['antispambox']
        account = config['account']
        return (config.get('enabled') in (True, 'True')
                and account.get('server') not in (None, '', 'imap.example.net')
                and bool(account.get('user')) and bool(account.get('password')))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def prepare_data(path=DATA):
    """Share classifier storage with Redis without granting world-write access."""
    spam_uid = pwd.getpwnam('debian-spamd').pw_uid
    redis_uid = pwd.getpwnam('redis').pw_uid
    mail_gid = grp.getgrnam('mail').gr_gid
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError('Classifier directory must not be a symbolic link')
    os.chown(path, spam_uid, mail_gid)
    path.chmod(0o2770)
    for item in path.iterdir():
        if item.name.startswith('bayes') or item.name == 'dump.rdb':
            if item.is_symlink():
                raise RuntimeError('Classifier data files must not be symbolic links')
            if item.is_file():
                owner = redis_uid if item.name == 'dump.rdb' else spam_uid
                os.chown(item, owner, mail_gid)
                item.chmod(0o660)


def configure():
    """Build-time service configuration for Debian's separate spamd package."""
    name = update_rules.spamd_service_name()
    defaults = pathlib.Path('/etc/default', name)
    text = defaults.read_text()
    options = 'OPTIONS="--allow-tell --max-children 5 --helper-home-dir -u debian-spamd -x --virtual-config-dir=/var/spamassassin --listen=127.0.0.1 --port=783"'
    text, count = re.subn(r'(?m)^OPTIONS=.*$', lambda _: options, text)
    if not count:
        text = text.rstrip('\n') + '\n' + options + '\n'
    defaults.write_text(text)
    log_config = pathlib.Path('/etc/rsyslog.conf')
    log_config.write_text('\n'.join('# Kernel logging is not used inside this container.'
                         if 'load="imklog"' in line else line
                         for line in log_config.read_text().splitlines()) + '\n')
    prepare_data()


def start_daemon(command, **options):
    return subprocess.Popen(command, start_new_session=True, **options)


def stop_process(child, group=False):
    if child.poll() is not None:
        return
    try:
        if group:
            os.killpg(child.pid, signal.SIGTERM)
        else:
            child.terminate()
        child.wait(timeout=15)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        if group:
            os.killpg(child.pid, signal.SIGKILL)
        else:
            child.kill()
        child.wait(timeout=5)


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())
    learning_compat.apply()
    update_rules.install_schedule()
    prepare_data()
    ACCOUNT.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not ACCOUNT.exists():
        ACCOUNT.write_bytes(pathlib.Path('/root/imap_accounts.json').read_bytes())
        ACCOUNT.chmod(0o600)
    runtime = pathlib.Path('/run/antispambox')
    runtime.mkdir(mode=0o700, exist_ok=True)
    runtime.chmod(0o700)
    for name, owner in (('/run/rspamd', '_rspamd'), ('/run/redis', 'redis'), ('/var/log/rspamd', '_rspamd'),
                        ('/var/lib/rspamd', '_rspamd')):
        directory = pathlib.Path(name)
        directory.mkdir(parents=True, exist_ok=True)
        user = pwd.getpwnam(owner)
        os.chown(directory, user.pw_uid, user.pw_gid)
    redis = pwd.getpwnam('redis')
    daemons, jobs = [], []
    scanner = None
    try:
        daemons.append(('rsyslog', start_daemon(['/usr/sbin/rsyslogd', '-n', '-i', '/run/rsyslogd.pid'])))
        daemons.append(('redis', start_daemon(['/usr/bin/redis-server', '/etc/redis/redis.conf',
                        '--daemonize', 'no', '--supervised', 'no', '--logfile', ''],
                       user=redis.pw_uid, group=redis.pw_gid,
                       extra_groups=[grp.getgrnam('mail').gr_gid], cwd='/')))
        daemons.append(('rspamd', start_daemon(['/usr/bin/rspamd', '-f', '-u', '_rspamd', '-g', '_rspamd'])))
        daemon = start_daemon(SPAMD_ARGS)
        daemons.append(('spamd', daemon))
        update_rules.SPAMD_PID.write_text(str(daemon.pid) + '\n')
        update_rules.SPAMD_PID.chmod(0o600)
        daemons.append(('lighttpd', start_daemon(['/usr/sbin/lighttpd', '-D', '-f', '/etc/lighttpd/lighttpd.conf'])))
        daemons.append(('cron', start_daemon(['/usr/sbin/cron', '-f'])))
        for attempt in range(30):
            for name, child in daemons:
                if child.poll() is not None:
                    raise RuntimeError('Daemon ' + name + ' exited during startup')
            if all(healthcheck.check().values()):
                break
            if STOP.wait(1):
                return 0
        else:
            raise RuntimeError('Filter daemons did not become ready')
        jobs.append(subprocess.Popen([sys.executable, '/root/update_rules.py'], start_new_session=True))
        if account_enabled():
            scanner = subprocess.Popen([sys.executable, '/root/antispambox.py'], start_new_session=True)
            jobs.append(scanner)
            LOGGER.info('Mailbox scanner started')
        else:
            LOGGER.info('Mailbox scanning is disabled; configure and enable the account volume')
        while not STOP.wait(2):
            for name, child in daemons:
                if child.poll() is not None:
                    raise RuntimeError('Daemon ' + name + ' exited unexpectedly')
            if scanner is not None and scanner.poll() is not None:
                raise RuntimeError('Mailbox scanner exited unexpectedly')
        return 0
    finally:
        for child in reversed(jobs):
            stop_process(child, group=True)
        for name, child in reversed(daemons):
            stop_process(child)
        update_rules.SPAMD_PID.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--configure', action='store_true')
    args = parser.parse_args()
    if args.configure:
        configure()
    else:
        try:
            raise SystemExit(main())
        except (RuntimeError, OSError) as error:
            LOGGER.error('%s', error)
            raise SystemExit(1)
