"""Local daemon health only; no mailbox login, message fetch or external network."""
import json
import socket
import urllib.request


def exchange(port, command, expected):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1) as client:
            client.settimeout(1)
            client.sendall(command)
            return expected in client.recv(512)
    except OSError:
        return False


def check():
    result = {
        'redis': exchange(6379, b'*1\r\n$4\r\nPING\r\n', b'+PONG'),
        'spamd': exchange(783, b'PING SPAMC/1.5\r\n\r\n', b'PONG'),
    }
    try:
        with urllib.request.urlopen('http://127.0.0.1:11334/ping', timeout=1) as response:
            result['rspamd'] = response.status == 200
    except (OSError, ValueError):
        result['rspamd'] = False
    return result


if __name__ == '__main__':
    result = check()
    print(json.dumps(result))
    raise SystemExit(0 if all(result.values()) else 1)
