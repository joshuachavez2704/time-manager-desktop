import time
import threading

from src.tracker import get_active_window_process
from src.utils import BROWSER_PROCESSES, WINDOWS_SYSTEM_PROCESSES, extract_domain


class TrackerService:
    """Runs the same polling loop main.py used to run inline, but as a
    start/stop-able background thread so a GUI can own the process lifetime
    instead of blocking on it."""

    def __init__(self, db, enforcer, focus_enforcer=None, poll_interval: float = 1.0):
        self.db = db
        self.enforcer = enforcer
        self.focus_enforcer = focus_enforcer
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop_event.set()

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        from src import tracker  # local import: current_browser_url is read live off this module

        last_check_time = time.time()
        while not self._stop_event.is_set():
            # Sleep in small slices so stop() takes effect within ~0.25s
            # instead of waiting out a full poll_interval.
            if self._stop_event.wait(timeout=self.poll_interval):
                break

            current_time = time.time()
            elapsed_seconds = int(round(current_time - last_check_time))
            last_check_time = current_time

            if elapsed_seconds <= 0:
                continue

            active_process = get_active_window_process().lower()

            # Windows shell/OS chrome (search flyout, lock screen, etc.) --
            # never logged as time spent, and skipped before enforcement
            # too so it's simply invisible to Narrowgate rather than
            # relying solely on FocusSession.SAFE_PROCESSES to protect it.
            if active_process in WINDOWS_SYSTEM_PROCESSES:
                continue

            # Focus Session enforcement is independent of daily-limit
            # tracking below -- it runs whenever a session is active,
            # regardless of which branch the time-logging falls into.
            if self.focus_enforcer and active_process != "unknown":
                self.focus_enforcer.check(active_process)

            if active_process in BROWSER_PROCESSES:
                domain = extract_domain(tracker.current_browser_url)
                if domain:
                    self.db.add_time_sample(domain, "WEBSITE", seconds=elapsed_seconds)
                else:
                    self.db.add_time_sample(active_process, "APP", seconds=elapsed_seconds)
            elif active_process != "unknown":
                self.db.add_time_sample(active_process, "APP", seconds=elapsed_seconds)

            self.enforcer.check_and_enforce()
