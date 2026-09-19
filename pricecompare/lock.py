import os
import time
from pathlib import Path


class LockError(Exception):
    pass


class RunLock:
    """Prevents concurrent runs. A lock older than stale_minutes (or of a dead pid) is taken over."""
    def __init__(self, path, stale_minutes=60):
        self.path, self.stale = Path(path), stale_minutes * 60

    def _alive(self, pid):
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, ValueError):
            return False
        except PermissionError:
            return True

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                    pid = int(self.path.read_text() or 0)
                except (OSError, ValueError):
                    age, pid = self.stale + 1, 0
                if age > self.stale or not self._alive(pid):
                    self.path.unlink(missing_ok=True)
                    continue
                raise LockError(f"another run is active (lock {self.path}, pid {pid})")
        raise LockError(f"could not acquire lock {self.path}")

    def __exit__(self, *a):
        self.path.unlink(missing_ok=True)
