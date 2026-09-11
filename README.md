# Narrowgate

A Windows desktop app (paired with a small Chrome extension) for tracking how much time you spend on apps and websites, setting daily limits, and locking yourself down to an allowlist for a set stretch of time with Focus Sessions. Everything is stored locally in a SQLite database on your own machine -- nothing is ever sent anywhere else.

## Running

Install dependencies (inside your venv): `pip install -r requirements.txt`

- `python app.py` — the real app: a system-tray GUI (Today/History/Limits tabs, in-app warning popups) that starts tracking automatically. This is what you'll normally run day to day.
- `python -m src.main` — headless/console mode, same tracking loop with no window, useful for debugging.
- `python view_stats.py` — quick one-off printout of today's totals without starting anything.
- `python test_window.py` — live console printout of the detected foreground process + current browser URL, for diagnosing the extension/daemon connection.

The Chrome extension (unpacked from `extension/`) talks to whichever of `app.py`/`src.main`/`test_window.py` you have running — only run one of them at a time, since they all bind the same port (8080).

Limits (`Limits` tab in the app, or `TimeTrackerDB.set_limit()`) are stored in the database now instead of being hardcoded, so edits take effect immediately without restarting.

A hardcoded list of Windows shell/OS processes (`WINDOWS_SYSTEM_PROCESSES` in `src/utils.py` — Start menu search, the lock screen, the IME/emoji panel, core session processes, and similar) is never tracked as time spent and never closed by a Focus Session, regardless of your allowlist. This isn't something you edit from the app; if you find another background Windows process that needs the same treatment, add its `.exe` name to that set in `src/utils.py` directly.

## Focus Sessions

Separate from the daily time-limit tracking above: the `Focus` tab lets you lock down to an allowlist of apps and websites for a set number of minutes. Add process names (`code.exe`) and/or domains (`github.com`) to the two lists, set a duration, and hit **Start Focus Session**.

While a session is running: any foreground app not on the allowed list gets closed immediately (same mechanism as a daily-limit breach), and any browser tab whose domain isn't on the allowed list gets redirected to a local "blocked" page showing how much time is left — the tab itself isn't closed, so nothing you had open is lost, and navigating elsewhere from that page works fine if the destination is also blocked-and-redirected in turn.

Every app/domain you've ever added shows up as a checkbox in its list (most recently used first), so you don't have to retype `code.exe` or `github.com` every time — just check the ones you want for this session. Typing something new into the box below a list and clicking **Add** (or pressing Enter) adds and checks it, and remembers it for next time too. Click the **✕** next to an entry to forget it for good. This history is separate from `FocusSession` itself — the *names* persist across restarts, but whether a session is currently running still doesn't (see below).

While a session is running, a small always-on-top box appears in the bottom-left corner of your screen showing the time remaining, with its own **Pause**/**Resume** button — so you can pause without switching back to the main window (which may be minimized to the tray). Pausing freezes the countdown exactly where it was (it doesn't keep ticking down while paused) and lifts enforcement entirely: apps stop getting closed and browser tabs stop getting redirected until you resume, at which point the countdown picks back up from where it left off. The same Pause/Resume control is also on the Focus tab itself. Pausing is *not* the same as stopping — the session, its allowlist, and its remaining time are all still there; only Stop actually ends it.

A few things worth knowing:

- A handful of processes (`explorer.exe`, `dwm.exe`, the app itself, `python.exe`/`pythonw.exe`) are always allowed regardless of your list, so the session can't break your desktop shell or make itself unstoppable.
- If you allow at least one website, your browser's process itself stays open (so it can host the allowed tab) — only individual disallowed *tabs* get redirected, rather than the whole browser being closed. If you allow zero websites, the browser process is treated like any other disallowed app and gets closed if you switch to it.
- The session lives only in memory — closing the app (or the packaged .exe) ends an in-progress session rather than resuming it on next launch. This is deliberate: it keeps the feature simple, at the cost of "just restart the app" being a way to end a session early.
- Tab blocking depends on the daemon (`app.py`, or the `.exe`) actually running, since that's what the extension polls — if it's not running, tabs are left alone (fails open, not closed).

## Building a standalone .exe

So you don't need to open a shell and run `python app.py` every time:

```powershell
.\build.ps1
```

This installs PyInstaller and produces `dist\Narrowgate.exe` — a single file with Python and all dependencies bundled in, launchable by double-clicking, no venv activation needed. Re-run `.\build.ps1` any time you change the source to rebuild it.

Then install it and create a Desktop and Start Menu shortcut for it:

```powershell
.\make_shortcuts.ps1
```

This copies `dist\Narrowgate.exe` into `%LOCALAPPDATA%\Narrowgate\` and points the shortcuts there, rather than at the exe still sitting in this project folder — if your project lives on a `\\wsl.localhost\...` path (or any network path), a shortcut pointing directly at it only works while that path is reachable (e.g. WSL is running), so this keeps the installed copy independent of that. Re-run `.\make_shortcuts.ps1` after every `.\build.ps1` to refresh the installed copy with your latest build.

Both scripts need script execution allowed for the session first, same as activating the venv:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

The .exe is windowed (no console). If it ever fails to start, check `%LOCALAPPDATA%\Narrowgate\narrowgate.log` — that's where anything that would normally print to a terminal (including startup errors) gets redirected instead, since a windowed app has no console to print to.
