import time
import threading
from src.database import TimeTrackerDB
from src.tracker import start_http_server, get_active_window_process
from src import tracker
from src.enforcer import LimitEnforcer
from src.utils import extract_domain

def main():
    db = TimeTrackerDB()
    enforcer = LimitEnforcer(db)

    # Start extension listener
    server_thread = threading.Thread(target=start_http_server, daemon=True)
    server_thread.start()
    print("Narrowgate daemon running. Press Ctrl+C to exit.")

    browsers = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}
    last_check_time = time.time()

    try:
        while True:
            time.sleep(1)
            
            # Calculate actual elapsed seconds to eliminate sleep drift
            current_time = time.time()
            elapsed_seconds = int(round(current_time - last_check_time))
            last_check_time = current_time

            if elapsed_seconds <= 0:
                continue

            active_process = get_active_window_process().lower()

            if active_process in browsers:
                domain = extract_domain(tracker.current_browser_url)
                if domain:
                    db.add_time_sample(domain, "WEBSITE", seconds=elapsed_seconds)
                else:
                    # Fallback to logging browser process if URL isn't captured
                    db.add_time_sample(active_process, "APP", seconds=elapsed_seconds)
            elif active_process != "unknown":
                db.add_time_sample(active_process, "APP", seconds=elapsed_seconds)

            enforcer.check_and_enforce()

    except KeyboardInterrupt:
        print("\nStopping Narrowgate.")

if __name__ == "__main__":
    main()