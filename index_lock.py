"""Serialize local index replacement and embedding installation on Linux."""
from contextlib import contextmanager
import fcntl
from pathlib import Path


@contextmanager
def index_lock(db_path: Path):
    path = Path(db_path).expanduser().resolve()
    with path.with_name(path.name + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
