"""Offline Docker smoke test; only disposable volumes and synthetic data are used."""
import json
import re
import subprocess
import sys
import time
import uuid


def docker(*args, check=True, timeout=120):
    return subprocess.run(['docker', *args], check=check, capture_output=True, text=True, timeout=timeout)


def ready(container):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        state = json.loads(docker('inspect', '--format', '{{json .State}}', container).stdout)
        if not state.get('Running'):
            raise RuntimeError('Smoke container exited before becoming ready')
        if state.get('Health', {}).get('Status') == 'healthy':
            return
        time.sleep(2)
    raise RuntimeError('Smoke container did not become healthy')


def main(image):
    container = None
    try:
        name = 'antispambox-smoke-' + uuid.uuid4().hex[:12]
        result = docker('run', '--detach', '--network', 'none', '--name', name, image)
        identifier = result.stdout.strip()
        if not re.fullmatch(r'[0-9a-f]{64}', identifier):
            raise RuntimeError('Docker did not return a container identifier')
        container = identifier
        ready(container)
        docker('exec', container, 'python3', '/root/healthcheck.py')
        learn = """import urllib.request,json
message=b'From: sender@example.invalid\\r\\nTo: receiver@example.invalid\\r\\nSubject: Synthetic smoke fixture\\r\\n\\r\\nThis isolated synthetic training fixture contains enough unique words for a classifier smoke check.\\r\\n'
request=urllib.request.Request('http://127.0.0.1:11334/learnspam',data=message,headers={'Content-Type':'message/rfc822'})
with urllib.request.urlopen(request,timeout=10) as response:
    result=json.load(response)
assert result.get('success') is True, 'Classifier did not confirm learning'
"""
        docker('exec', container, 'python3', '-c', learn)
        docker('exec', container, 'python3', '-c', 'import update_rules; raise SystemExit(update_rules.reload_foreground_spamd())')
        docker('exec', container, 'python3', '/root/healthcheck.py')
        docker('exec', container, 'redis-cli', 'SET', 'antispambox:smoke', 'persistent')
        docker('stop', '--time', '60', container)
        code = docker('inspect', '--format', '{{.State.ExitCode}}', container).stdout.strip()
        if code != '0':
            raise RuntimeError('Container did not shut down cleanly')
        docker('start', container)
        ready(container)
        value = docker('exec', container, 'redis-cli', '--raw', 'GET', 'antispambox:smoke').stdout.strip()
        if value != 'persistent':
            raise RuntimeError('Redis data did not survive a clean restart')
        print('Smoke passed: local daemons, classifier learning, reload, graceful shutdown and Redis persistence')
    except Exception:
        if container:
            logs = docker('logs', '--tail', '80', container, check=False)
            print(logs.stdout + logs.stderr, file=sys.stderr)
        raise
    finally:
        if container:
            docker('rm', '--force', '--volumes', container, check=False)


if __name__ == '__main__':
    main(sys.argv[1])
