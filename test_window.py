# test_window.py
import time
import threading
from src.tracker import get_active_window_process, start_http_server
from src import tracker

# Start the same HTTP listener main.py runs, so the Chrome extension has
# something to POST the current URL to. Without this, tracker.current_browser_url
# never changes from its default and this script will always print "None".
# NOTE: don't run this at the same time as main.py — both bind port 8080.
server_thread = threading.Thread(target=start_http_server, daemon=True)
server_thread.start()

print("Monitoring active window... Press Ctrl+C to stop.\n")
print(f"{'Active Process':<30} | {'Current Browser URL'}")
print("-" * 65)

try:
    while True:
        process = get_active_window_process()
        url = tracker.current_browser_url
        print(f"{process:<30} | {url}")
        time.sleep(1)
except KeyboardInterrupt:
    print("\nTracker test stopped.")