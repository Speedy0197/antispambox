"""Daily rule updates with native exit handling, lint, reload and a status record."""
import datetime
import fcntl
import json
import os
import pathlib
import re
import signal
import stat
import subprocess
import sys
import tempfile

CRON = ('# Antispambox rule updates, daily 00:05 in the container timezone.\n'
        f'5 0 * * * root {sys.executable} {pathlib.Path(__file__).resolve()} > /dev/null 2>&1\n')
STATUS = pathlib.Path('/var/spamassassin/bayesdb/rule-update-status.json')
LOG = pathlib.Path('/var/log/antispambox-rule-update.log')
LOCK = pathlib.Path('/run/lock/antispambox-rule-update.lock')
SPAMD_PID = pathlib.Path('/run/antispambox/spamd.pid')


def disable_daily_updates(path):
    if not path.is_file():
        return False
    original = path.read_text()
    text, count = re.subn(r'(?m)^CRON=[01]$', 'CRON=0', original)
    if count > 1:
        raise RuntimeError('Multiple Debian updater toggles found')
    if not count:
        text = original.rstrip('\n') + '\nCRON=0\n'
    if text != original:
        path.write_text(text)
    return True


def spamd_service_name():
    for name in ('spamd', 'spamassassin'):
        if pathlib.Path('/etc/init.d', name).is_file():
            return name
    raise RuntimeError('The SpamAssassin daemon package is not installed')


def install_schedule():
    found = [disable_daily_updates(pathlib.Path('/etc/default', name))
             for name in ('spamd', 'spamassassin')]
    if not any(found):
        raise RuntimeError('No supported SpamAssassin daemon defaults found')
    cron = pathlib.Path('/etc/cron.d/antispambox-rules')
    cron.write_text(CRON)
    cron.chmod(0o644)


def execute(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        code, output = result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        code, output = 124, 'Command exceeded its update timeout'
    previous = LOG.read_text()[-65536:] if LOG.exists() else ''
    LOG.write_text(previous + '\n' + command[0] + ' exit=' + str(code) + '\n' + output[-16384:])
    LOG.chmod(0o600)
    return code


def channels():
    return [line.strip() for line in pathlib.Path(__file__).with_name('sa-channels').read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def reload_foreground_spamd():
    try:
        descriptor = os.open(SPAMD_PID, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor) as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
                return 1
            pid = int(handle.read(32).strip())
        if pid <= 1:
            return 1
        arguments = pathlib.Path('/proc', str(pid), 'cmdline').read_bytes().split(b'\0')
        if not any(pathlib.Path(arg.decode(errors='replace')).name == 'spamd'
                   or arg.startswith(b'spamd ') for arg in arguments):
            return 1
        os.kill(pid, signal.SIGHUP)
        return 0
    except (OSError, ValueError):
        return 1


def update(reload_required=True, activation_pending=False):
    main = execute(['/usr/bin/sa-update'])  # Native default GPG verification.
    # Preserve existing third-party trust policy and isolate each channel's result.
    results = {'updates.spamassassin.org': main}
    for channel in channels():
        results[channel] = execute(['/usr/bin/sa-update', '--nogpg', '--channel', channel])
    changed = any(code in (0, 3) for code in results.values())
    failed = any(code not in (0, 1) for code in results.values())
    good = any(code in (0, 1, 3) for code in results.values())
    report = {'channels': results, 'changed': changed, 'reloaded': False,
              'activation_pending': bool(changed or activation_pending),
              'state': 'partial' if failed and good else 'error' if failed else 'ok'}
    if changed or activation_pending:
        lint = execute(['/usr/bin/spamassassin', '--lint'])
        report['lint_exit'] = lint
        if lint != 0:
            report['state'] = 'error'
        elif reload_required:
            if os.path.lexists(SPAMD_PID):
                reload_code = reload_foreground_spamd()
            else:
                running = execute(['/usr/sbin/service', spamd_service_name(), 'status'])
                reload_code = execute(['/usr/sbin/service', spamd_service_name(), 'reload']) if running == 0 else running
            report['reload_exit'] = reload_code
            report['reloaded'] = reload_code == 0
            report['activation_pending'] = not report['reloaded']
            if not report['reloaded']:
                report['state'] = 'error'
        else:
            # Startup calls this before starting spamd, which will load these rules.
            report['activation_pending'] = False
    return report


def read_status():
    try:
        descriptor = os.open(STATUS, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor) as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return {'activation_pending': True}
            text = handle.read(65537)
            if len(text) > 65536:
                return {'activation_pending': True}
            result = json.loads(text)
            return result if isinstance(result, dict) else {'activation_pending': True}
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        return {'activation_pending': True}


def write_status(result):
    descriptor, temporary = tempfile.mkstemp(prefix='.rule-update-status-', dir=STATUS.parent)
    try:
        with os.fdopen(descriptor, 'w') as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(result, handle)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, STATUS)
    finally:
        pathlib.Path(temporary).unlink(missing_ok=True)


def run(reload_required=True):
    lock = LOCK
    lock.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(descriptor, 'a') as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise RuntimeError('Unsafe rule-update lock file')
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'state': 'busy'}), flush=True)
            return 0
        previous = read_status()
        result = update(reload_required, previous.get('activation_pending', False))
        result['checked_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if previous.get('last_success'):
            result['last_success'] = previous['last_success']
        if result['state'] == 'ok':
            result['last_success'] = result['checked_at']
        write_status(result)
        print(json.dumps(result), flush=True)
        return 0 if result['state'] == 'ok' else 1


if __name__ == '__main__':
    if sys.argv[1:] == ['--install-schedule']:
        install_schedule()
    else:
        raise SystemExit(run())
