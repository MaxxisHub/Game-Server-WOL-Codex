import subprocess
import sys
import threading
import time
from datetime import datetime


def log(msg: str) -> None:
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts} UTC] {msg}", flush=True)


def sh(cmd: list[str]) -> tuple[int, str, str]:
    """Run a command and return (rc, stdout, stderr)."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    return p.returncode, out, err


def ping_host(host: str, timeout_sec: int = 1) -> bool:
    # Use system ping (SUID root typically present). One ping, wait timeout.
    rc, out, _ = sh(["ping", "-c", "1", "-w", str(timeout_sec), host])
    return rc == 0


class RepeatedTimer:
    def __init__(self, interval: float, func, *args, **kwargs):
        self.interval = interval
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self):
        next_time = time.time() + self.interval
        while not self._stop.is_set():
            now = time.time()
            if now >= next_time:
                try:
                    self.func(*self.args, **self.kwargs)
                except Exception as e:
                    log(f"Timer function raised: {e}")
                next_time = now + self.interval
            time.sleep(0.05)

