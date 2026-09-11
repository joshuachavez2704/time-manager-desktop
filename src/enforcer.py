from src.utils import send_os_notification, kill_process

# Keys are lowercase to match the lowercase target_name values that actually
# get written to daily_usage (main.py lowercases process names, and
# utils.extract_domain() lowercases domains) -- a mismatched case here used
# to mean a limit would silently never trigger.
DEFAULT_LIMITS = {
    "leagueclientux.exe": 3600,
    "discord.exe": 5400,
    "youtube.com": 1800,
}


class LimitEnforcer:
    def __init__(self, db, on_warning=None):
        """
        db: TimeTrackerDB instance. Limits are read from db.get_limits() on
            every check (not passed in statically), so edits made through a
            GUI take effect immediately without restarting the tracker.
        on_warning: optional callback(title: str, message: str, level: str)
            invoked in addition to the OS notification, where level is
            "warning" (80%) or "breach" (100%+). Use this to hook up an
            in-app popup -- it's called from whatever thread runs
            check_and_enforce(), so a Tk-based GUI must marshal it onto the
            main thread itself (e.g. via a thread-safe queue) rather than
            touching widgets directly from here.
        """
        self.db = db
        self.on_warning = on_warning
        self.warned_targets = set()
        self.breached_targets = set()
        self.db.seed_default_limits(DEFAULT_LIMITS)

    def check_and_enforce(self):
        limits = self.db.get_limits()
        today_usage = self.db.get_daily_summary()

        for target_name, target_type, duration in today_usage:
            if target_name not in limits:
                continue

            limit_seconds = limits[target_name]
            if limit_seconds <= 0:
                continue

            if duration >= (limit_seconds * 0.8) and duration < limit_seconds \
                    and target_name not in self.warned_targets:
                self._notify(
                    "Narrowgate Warning",
                    f"You have used 80% of your limit for {target_name}.",
                    level="warning",
                )
                self.warned_targets.add(target_name)

            if duration >= limit_seconds and target_name not in self.breached_targets:
                self.breached_targets.add(target_name)
                if target_type == "APP":
                    self._notify(
                        "Narrowgate Limit Breached",
                        f"Limit reached for {target_name}. Closing application.",
                        level="breach",
                    )
                    kill_process(target_name)
                else:
                    # There's no way to close just one browser tab from here,
                    # so websites just get told about the breach instead of
                    # being force-closed.
                    self._notify(
                        "Narrowgate Limit Breached",
                        f"Limit reached for {target_name}.",
                        level="breach",
                    )

    def reset_daily_state(self):
        """Call this at day rollover so warnings/breaches can fire again."""
        self.warned_targets.clear()
        self.breached_targets.clear()

    def _notify(self, title, message, level):
        send_os_notification(title, message)
        if self.on_warning:
            try:
                self.on_warning(title, message, level)
            except Exception:
                pass
