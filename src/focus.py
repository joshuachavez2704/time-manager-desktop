import time
import threading

from src.utils import BROWSER_PROCESSES, WINDOWS_SYSTEM_PROCESSES, kill_process, send_os_notification

# Never kill these, even during an active Focus Session -- killing them
# would break the OS shell or this app's own process, which would either
# crash your desktop or make the Focus Session impossible to stop.
# WINDOWS_SYSTEM_PROCESSES (see utils.py) covers Windows' own shell/search/
# lock-screen chrome; the rest here are Narrowgate-specific.
SAFE_PROCESSES = WINDOWS_SYSTEM_PROCESSES | {
    "narrowgate.exe",      # the packaged app itself
    "python.exe",         # covers running via `python app.py` in dev
    "pythonw.exe",
}


class FocusSession:
    """A time-boxed allowlist of apps/websites, held only in memory: it is
    not written to the database, so closing the app ends whatever session
    was in progress rather than resuming it on the next launch (a
    deliberate choice -- see README).

    Read/written from two threads (the Tk GUI thread starts/stops it and
    polls it for the countdown display; TrackerService's background thread
    checks it every tick), so all access goes through a lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.end_time = None
        self.allowed_apps = set()
        self.allowed_domains = set()
        self.paused = False
        self._pause_started = None

    def start(self, duration_minutes, allowed_apps, allowed_domains):
        with self._lock:
            self.end_time = time.time() + max(0.0, float(duration_minutes)) * 60
            self.allowed_apps = {a.strip().lower() for a in allowed_apps if a and a.strip()}
            self.allowed_domains = {d.strip().lower() for d in allowed_domains if d and d.strip()}
            self.paused = False
            self._pause_started = None

    def stop(self):
        with self._lock:
            self.end_time = None
            self.allowed_apps = set()
            self.allowed_domains = set()
            self.paused = False
            self._pause_started = None

    def pause(self):
        """Temporarily lifts enforcement without ending the session or
        losing the time already counted down. The countdown freezes at
        whatever remaining_seconds() reads right now -- it does NOT keep
        burning down while paused -- and picks back up from exactly there
        on resume()."""
        with self._lock:
            if self.end_time is None or self.paused:
                return
            self.paused = True
            self._pause_started = time.time()

    def resume(self):
        """Undoes pause(): pushes end_time out by however long the session
        was paused, so the remaining time afterward is exactly what it was
        the moment pause() was called."""
        with self._lock:
            if not self.paused:
                return
            elapsed = time.time() - self._pause_started
            self.end_time += elapsed
            self.paused = False
            self._pause_started = None

    @property
    def is_active(self):
        """True while a session exists and hasn't run out. Stays True
        through a pause -- a paused session hasn't ended, it just isn't
        enforcing right now -- and pausing freezes the deadline so a long
        pause can't let the session silently expire out from under you."""
        with self._lock:
            if self.end_time is None:
                return False
            return self.paused or time.time() < self.end_time

    @property
    def is_enforcing(self):
        """True only when a session is active AND not paused. This -- not
        is_active -- is what should gate actually restricting anything:
        FocusEnforcer killing an app, or the extension blocking a tab."""
        with self._lock:
            return self.end_time is not None and not self.paused and time.time() < self.end_time

    @property
    def is_paused(self):
        with self._lock:
            return self.paused

    def remaining_seconds(self):
        with self._lock:
            if self.end_time is None:
                return 0
            if self.paused:
                return max(0, int(round(self.end_time - self._pause_started)))
            return max(0, int(round(self.end_time - time.time())))

    def is_app_allowed(self, process_name):
        name = process_name.lower()
        if name in SAFE_PROCESSES:
            return True
        with self._lock:
            if self.end_time is None or self.paused or time.time() >= self.end_time:
                return True  # no active/enforcing session -- nothing to restrict
            if name in self.allowed_apps:
                return True
            # A browser process stays open at the OS level as long as at
            # least one website is allowed -- individual disallowed tabs
            # are handled by the extension (redirected), not by killing
            # the whole browser and every allowed tab along with it.
            if self.allowed_domains and name in BROWSER_PROCESSES:
                return True
            return False

    def is_domain_allowed(self, domain):
        """Mirrors the subdomain-aware check background.js does for actual
        tab enforcement -- allowing "google.com" also covers
        "docs.google.com", "mail.google.com", etc. Not called by the tab
        blocking itself (that lives in the extension, which the daemon
        can't reach into), but kept here so the same rule is testable and
        documented in one place in the Python code too."""
        domain = domain.lower()
        with self._lock:
            return any(domain == allowed or domain.endswith("." + allowed) for allowed in self.allowed_domains)

    def status(self):
        """JSON-serializable snapshot for the extension's /focus-status
        poll. "active" reports whether the session is currently ENFORCING
        (i.e. is_enforcing) rather than merely is_active, so pausing makes
        the extension stop blocking tabs -- exactly what "pause" should
        mean -- without needing any change on the extension side, since it
        already just checks status.active."""
        with self._lock:
            has_session = self.end_time is not None and (self.paused or time.time() < self.end_time)
            enforcing = self.end_time is not None and not self.paused and time.time() < self.end_time
            if not has_session:
                remaining = 0
            elif self.paused:
                remaining = max(0, int(round(self.end_time - self._pause_started)))
            else:
                remaining = max(0, int(round(self.end_time - time.time())))
            return {
                "active": enforcing,
                "paused": self.paused,
                "remaining_seconds": remaining,
                "allowed_domains": sorted(self.allowed_domains),
            }


class FocusEnforcer:
    """Closes the foreground app whenever a Focus Session is active and
    that app isn't allowed. Call check(active_process) once per tracking
    tick -- it's a no-op unless a session is currently running."""

    NOTIFY_COOLDOWN_SECONDS = 5.0

    def __init__(self, session: FocusSession, on_notify=None):
        """
        on_notify: optional callback(title, message, level) for hooking up
        an in-app popup, same shape as LimitEnforcer's on_warning.
        """
        self.session = session
        self.on_notify = on_notify
        self._last_notified = {}

    def check(self, active_process):
        if not self.session.is_active:
            return
        if self.session.is_app_allowed(active_process):
            return

        kill_process(active_process)

        now = time.time()
        if now - self._last_notified.get(active_process, 0) >= self.NOTIFY_COOLDOWN_SECONDS:
            self._last_notified[active_process] = now
            title = "Focus Session"
            message = f"{active_process} isn't on your allowed list for this Focus Session -- closed."
            send_os_notification(title, message)
            if self.on_notify:
                try:
                    self.on_notify(title, message, "focus")
                except Exception:
                    pass
