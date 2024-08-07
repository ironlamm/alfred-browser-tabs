import fcntl
import functools
import time
import errno
import os
from pathlib import Path

class LockFile:
    def __init__(self, lock_file_path, stale_age_sec=60):
        self.lock_file_path = Path(lock_file_path) if isinstance(lock_file_path, str) else lock_file_path
        self.lock_file = None
        self.stale_age_sec = stale_age_sec  # Fallback for unreadable lock files

    def acquire(self, is_retry=False):
        try:
            self.lock_file = self.lock_file_path.open('w')
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            
            # If we got here, we have the lock
            self.lock_file.write(str(os.getpid()))
            self.lock_file.flush()
            return True
        except IOError as e:
            if e.errno != errno.EWOULDBLOCK:
                raise
            
            # Lock is held, check if it's stale
            if self.is_stale() and not is_retry:
                self.break_lock()
                return self.acquire(is_retry=True)  # retry acquire
            
            self.lock_file.close()
            return False

    def release(self):
        if self.lock_file:
            fcntl.flock(self.lock_file, fcntl.LOCK_UN)
            self.lock_file.close()
            self.lock_file = None
            try:
                self.lock_file_path.unlink()
            except FileNotFoundError:
                pass  # File might be already removed

    def is_stale(self):
        try:
            pid = int(self.lock_file_path.read_text().strip())
            os.kill(pid, 0)  # check if process is running
        except FileNotFoundError:
            return True
        except ValueError:
            # If we can't read the file or its content is invalid
            return self._is_file_stale()
        except OSError as e:
            if e.errno == errno.ESRCH:  # No such process
                return True  # Process not running, consider it stale
            # For other errors, fall through to the general case

        # Process is running
        if self._is_file_stale():
            # Kill old process
            os.kill(pid, 9)
            return True
        return False

    def _is_file_stale(self):
        try:
            file_age = time.time() - self.lock_file_path.stat().st_mtime
            return file_age > self.stale_age_sec
        except FileNotFoundError:
            return True  # File doesn't exist, consider it stale

    def break_lock(self):
        try:
            self.lock_file_path.unlink()
        except FileNotFoundError:
            pass  # File might be already removed

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, type, value, traceback):
        self.release()

    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with self:
                return func(*args, **kwargs)
        return wrapper
