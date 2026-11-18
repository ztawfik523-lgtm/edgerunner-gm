import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from index_lock import index_lock


def test_index_lock_serializes_processes(tmp_path):
    db = tmp_path / 'rules.sqlite'
    code = '''
import fcntl,sys
with open(sys.argv[1], 'a') as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(7)
'''
    args = [sys.executable, '-c', code, str(db) + '.lock']
    with index_lock(db):
        assert subprocess.run(args, timeout=5).returncode == 7
    assert subprocess.run(args, timeout=5).returncode == 0
