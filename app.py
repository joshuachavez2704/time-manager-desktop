# app.py - Narrowgate desktop GUI entry point.
#
# This replaces manually running main.py in a terminal: it starts the same
# extension-listener HTTP server and tracking loop, but wraps them in a
# Tkinter window + system tray icon instead of a bare console loop.
#
# main.py, view_stats.py, and test_window.py still work standalone for
# headless/debugging use -- this is the "real app" on top of the same
# src/ modules.
import os
import sys

# When this is packaged into a windowed/no-console .exe (via PyInstaller's
# --windowed flag), sys.stdout/sys.stderr are None -- there's no console to
# write to. Any code that calls print() (e.g. enforcer.py's notification
# fallback) would then crash with "AttributeError: 'NoneType' object has no
# attribute 'write'" the first time it tried, silently, with no window and
# no error message. Redirect to a log file instead so:
#   1. print() keeps working instead of crashing.
#   2. Any startup crash is actually recorded somewhere findable.
if getattr(sys, "frozen", False):
    _log_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Narrowgate")
    os.makedirs(_log_dir, exist_ok=True)
    _log_file = open(os.path.join(_log_dir, "narrowgate.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = _log_file
    sys.stderr = _log_file

import queue
import threading
import traceback

from src.database import TimeTrackerDB
from src import tracker
from src.tracker import start_http_server
from src.enforcer import LimitEnforcer
from src.focus import FocusSession, FocusEnforcer
from src.service import TrackerService
from src.gui import NarrowgateApp


# Keeps the mutex handle alive for the life of the process -- Windows
# releases a named mutex automatically when the owning process exits (even
# if it crashes), so there's nothing to explicitly clean up on the way out,
# but the handle must not get garbage-collected while we're still running.
_single_instance_mutex = None


def _ensure_single_instance():
    """Refuses to start a second copy of the app.

    Without this, launching the shortcut more than once -- easy to do,
    since closing the window just minimizes it to the tray (see
    _on_close_button in gui.py) rather than exiting, so it's easy to think
    a launch didn't work and double-click again -- silently starts another
    full Narrowgate.exe. Only the FIRST one to launch actually wins
    tracker.py's HTTP server bind on port 8080; every later copy fails that
    bind (silently, in a background thread) and keeps running anyway, with
    its own independent, unreachable Focus Session. If you're looking at
    one of THOSE windows when you click "Start Focus Session," the Chrome
    extension -- which only ever talks to whichever process is holding
    port 8080 -- never learns about it, so nothing gets blocked. Multiple
    accumulated copies also means multiple independent trackers all
    fighting to log the same time samples.

    Windows-only (uses a named kernel mutex, the standard way to do this on
    Windows); a no-op everywhere else so dev/test runs on Linux/WSL are
    unaffected. Returns True if this process should proceed, False if
    another instance already owns the lock.
    """
    global _single_instance_mutex
    if sys.platform != "win32":
        return True

    import ctypes

    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _single_instance_mutex = kernel32.CreateMutexW(None, False, "Local\\NarrowgateSingleInstance")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        ctypes.windll.user32.MessageBoxW(
            None,
            "Narrowgate is already running.\n\n"
            "Check your system tray (the small icons near the clock) -- "
            "it's already open there.",
            "Narrowgate",
            0x40,  # MB_ICONINFORMATION
        )
        return False
    return True


def main():
    db = TimeTrackerDB()

    warning_queue = queue.Queue()

    def on_warning(title, message, level):
        # Called from the tracker service's background thread -- just hand
        # it off to the queue the Tk main loop polls, rather than touching
        # any widgets from this thread.
        warning_queue.put((title, message, level))

    enforcer = LimitEnforcer(db, on_warning=on_warning)

    # Focus Sessions are separate from the daily-limit tracking above: an
    # in-memory, time-boxed allowlist (not persisted -- see FocusSession's
    # docstring), started/stopped from the GUI's Focus tab. tracker.py's
    # HTTP server needs a reference to it too, since the extension polls
    # GET /focus-status to know whether to redirect a tab.
    focus_session = FocusSession()
    tracker.set_focus_session(focus_session)
    focus_enforcer = FocusEnforcer(focus_session, on_notify=on_warning)

    server_thread = threading.Thread(target=start_http_server, daemon=True)
    server_thread.start()

    service = TrackerService(db, enforcer, focus_enforcer=focus_enforcer)
    service.start()

    app = NarrowgateApp(db, service, warning_queue, focus_session=focus_session)
    app.run()


if __name__ == "__main__":
    if not _ensure_single_instance():
        sys.exit(0)
    try:
        main()
    except Exception:
        # With --windowed there's no console to see this in, so make sure
        # it lands in the log file (see the frozen-stdout redirect above)
        # instead of just vanishing.
        traceback.print_exc()
        raise
