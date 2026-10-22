"""Keep API integration jobs and accounts out of the running site's storage."""
import os
import sys
import tempfile
from pathlib import Path

_storage = None
_previous = {}


def pytest_configure(config):
    global _storage
    if 'aihoop.api' in sys.modules or 'aihoop.auth' in sys.modules:
        raise RuntimeError('Test storage must be selected before importing API/auth')
    _storage = tempfile.TemporaryDirectory(prefix='aihoop-pytest-')
    for key, subdir in [('AIHOOP_DATA_DIR', 'data'), ('AIHOOP_OUT_DIR', 'out')]:
        _previous[key] = os.environ.get(key)
        os.environ[key] = str(Path(_storage.name) / subdir)


def pytest_unconfigure(config):
    # Short API jobs may still run after a failed assertion; finish them before
    # removing temporary storage so they cannot recreate paths after cleanup.
    api = sys.modules.get('aihoop.api')
    if api is not None:
        api.POOL.shutdown(wait=True)
    for key, value in _previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    if _storage is not None:
        _storage.cleanup()
