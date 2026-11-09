"""Guard the legacy IRSD learner against caching failed rspamc commands."""
import ast
import pathlib
import sys

OLD = '    elif code == 1:\n        code = 6\n        orig_code = 6\n'
NEW = '    elif code != 0:\n        orig_code = code\n        code = -9999  # Failure must remain retryable, never cached as learned.\n'


def patch_source(source):
    if NEW in source and OLD not in source:
        return source
    if source.count(OLD) != 1:
        raise RuntimeError('Unexpected IRSD learner; refusing an unreviewed patch')
    result = source.replace(OLD, NEW)
    ast.parse(result)
    return result


def installed_module():
    candidates = set()
    for entry in sys.path:
        root = pathlib.Path(entry or '.')
        for pattern in ('irsd/spamproc.py', 'irsd*/irsd/spamproc.py'):
            candidates.update(path.resolve() for path in root.glob(pattern))
    if len(candidates) != 1:
        raise RuntimeError('Expected exactly one installed, unpacked IRSD module')
    return candidates.pop()


def apply():
    path = installed_module()
    source = path.read_text()
    patched = patch_source(source)
    if patched != source:
        path.write_text(patched)


if __name__ == '__main__':
    apply()
