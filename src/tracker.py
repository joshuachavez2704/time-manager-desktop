import sys
import json
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler

current_browser_url = "None"

# Set by app.py via set_focus_session() once a FocusSession exists. Stays
# None in headless/CLI mode (src.main), which doesn't offer Focus Sessions
# -- the /focus-status endpoint just reports "not active" in that case.
_focus_session = None


def set_focus_session(session):
    global _focus_session
    _focus_session = session


class ExtensionRequestHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path == '/focus-status':
            if _focus_session is not None:
                status = _focus_session.status()
            else:
                status = {"active": False, "remaining_seconds": 0, "allowed_domains": []}
            body = json.dumps(status).encode('utf-8')
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

    def do_POST(self):
        global current_browser_url
        if self.path == '/active-tab':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(body)
                current_browser_url = data.get('url', 'Unknown')
            except json.JSONDecodeError:
                pass

            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
        else:
            # Always send a response, even for unrecognized paths, so the
            # extension's fetch() doesn't hang waiting for a reply.
            self.send_response(404)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

    def log_message(self, format, *args):
        return

def start_http_server():
    # This is what the Chrome extension actually talks to -- if the bind
    # fails (most likely because another Narrowgate.exe is already
    # running and holding the port), this thread would otherwise die
    # silently and leave a fully-working GUI running that the extension can
    # never reach. Log it loudly instead of letting that happen quietly.
    # (app.py's single-instance lock should make this unreachable in normal
    # use, but this stays as a safety net.)
    try:
        server = HTTPServer(('localhost', 8080), ExtensionRequestHandler)
    except OSError:
        print(
            "[Narrowgate] Could not start the extension server on "
            "localhost:8080 -- is another copy of Narrowgate already "
            "running? The Chrome extension will not be able to reach this "
            "instance.",
            file=sys.stderr,
        )
        traceback.print_exc()
        return
    server.serve_forever()

def get_active_window_process():
    if sys.platform == 'win32':
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "Unknown"

        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        process_handle = kernel32.OpenProcess(0x1000, False, pid)
        if not process_handle:
            return "Unknown"

        buffer_size = 1024
        buffer = ctypes.create_unicode_buffer(buffer_size)
        size = ctypes.wintypes.DWORD(buffer_size)

        success = kernel32.QueryFullProcessImageNameW(process_handle, 0, buffer, ctypes.byref(size))
        kernel32.CloseHandle(process_handle)

        if success:
            return buffer.value.split('\\')[-1]
    return "Unknown"
