from urllib.parse import urlparse

import psutil
from plyer import notification

BROWSER_PROCESSES = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}

# Windows shell/OS chrome that isn't really something you "use" -- it's
# background plumbing that can briefly grab foreground focus (a search
# flyout, the lock screen, an IME popup) or just needs to never be killed
# outright. Hardcoded here rather than left for the user to add as a
# regular limit/allowlist entry, because killing or losing track of these
# can break the desktop shell or just isn't meaningful "screen time":
#   - TrackerService skips these entirely: no time gets logged against them.
#   - FocusSession never closes them, Focus Session or not (see focus.py's
#     SAFE_PROCESSES, which is this set plus a few Narrowgate-specific
#     entries like the app's own process).
# Deliberately conservative: things that host or could host a real app the
# user might actually want tracked/limited (ApplicationFrameHost.exe,
# SystemSettings.exe) are left OUT on purpose, even though they're also
# part of Windows, so tracking doesn't quietly go blind on real usage. Add
# more names here directly if something else needs the same treatment.
WINDOWS_SYSTEM_PROCESSES = {
    # Desktop shell / taskbar / Start menu / search
    "explorer.exe",             # desktop, taskbar, File Explorer shell host
    "dwm.exe",                  # Desktop Window Manager (compositor)
    "sihost.exe",                # Shell Infrastructure Host (Action Center support)
    "shellexperiencehost.exe",  # Start menu / Action Center UI host
    "startmenuexperiencehost.exe",  # Windows 11 Start menu
    "searchhost.exe",           # Windows 11 taskbar/Start search
    "searchapp.exe",            # Windows 10 search/Cortana UI
    "searchui.exe",             # older Windows 10 search UI name
    "widgets.exe",               # Windows 11 Widgets panel
    "widgetboard.exe",
    # Lock / login / input
    "lockapp.exe",               # lock screen
    "logonui.exe",               # sign-in screen
    "textinputhost.exe",         # touch keyboard / emoji panel / IME
    "ctfmon.exe",                 # text input framework, language bar
    # Background brokers / security chrome
    "runtimebroker.exe",         # permission broker for UWP apps (fires on prompts)
    "taskhostw.exe",              # hosts misc background Windows tasks
    "securityhealthsystray.exe", # Windows Security tray icon
    "smartscreen.exe",           # SmartScreen check UI
    # Core session/kernel processes -- these never actually own the
    # foreground window in practice, so this is defensive, not load-bearing
    "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe",
    "smss.exe", "svchost.exe", "fontdrvhost.exe", "audiodg.exe",
    "spoolsv.exe", "wmiprvse.exe", "dllhost.exe",
}


def extract_domain(url):
    """Normalize a URL down to a bare, lowercase, www-stripped domain.

    Returns None for anything that isn't a usable URL, so callers can
    fall back to logging the raw process name instead.
    """
    if not url or url == "None":
        return None
    # Ensure protocol exists so urlparse extracts netloc properly
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    try:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain if domain else None
    except Exception:
        return None


def send_os_notification(title, message):
    try:
        notification.notify(title=title, message=message, app_name="Narrowgate", timeout=5)
    except Exception:
        # No console in a --windowed build -- see app.py's stdout redirect,
        # which is what actually catches this print instead of crashing.
        print(f"[ALERT] {title}: {message}")


def kill_process(process_name):
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == process_name.lower():
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
