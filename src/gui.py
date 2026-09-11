import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import pystray
from PIL import Image, ImageDraw


# --- Theme -------------------------------------------------------------
# A small "clean modern light" palette plus a handful of reusable ttk style
# names (Card.*, Accent.*, Stat*.*). ttk keeps one Style registry per Tk
# interpreter, so configuring the base widget styles here (TFrame, TLabel,
# TButton, Treeview, TNotebook, ...) changes how every tab looks, not just
# Today -- even though Today is the only tab getting a bespoke layout built
# on top of it for now.
COLORS = {
    "bg": "#f5f6f8",          # window / page background
    "surface": "#ffffff",     # card / panel background
    "border": "#e3e5ea",
    "text": "#1f2430",
    "text_muted": "#6b7280",
    "stripe": "#f7f8fb",      # alternating row tint (barely off-white)
    "accent": "#3b6fed",
    "accent_soft": "#eaf0fe",
    "accent_text": "#2350c9",
    "danger": "#c23b3b",
    "danger_soft": "#fdecec",
}

FONT_FAMILY = "Segoe UI"


def _configure_style(root):
    root.configure(bg=COLORS["bg"])

    style = ttk.Style(root)
    # "clam" is the only built-in ttk theme that actually honors custom
    # widget colors everywhere -- Windows' native "vista"/"xpnative" themes
    # draw buttons/tabs/etc with real OS chrome and silently ignore most
    # style.configure() color options -- so it's the base on every platform
    # this runs on (including this sandbox, for testing).
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=COLORS["bg"], foreground=COLORS["text"],
                     font=(FONT_FAMILY, 10))
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
    style.configure("TLabelframe", background=COLORS["bg"], foreground=COLORS["text"],
                     bordercolor=COLORS["border"])
    style.configure("TLabelframe.Label", background=COLORS["bg"], foreground=COLORS["text_muted"],
                     font=(FONT_FAMILY, 9, "bold"))
    style.configure("TCheckbutton", background=COLORS["bg"], foreground=COLORS["text"])

    style.configure("Card.TFrame", background=COLORS["surface"], borderwidth=1,
                     relief="solid", bordercolor=COLORS["border"])
    style.configure("Card.TLabel", background=COLORS["surface"], foreground=COLORS["text"])

    style.configure("StatValue.TLabel", background=COLORS["surface"], foreground=COLORS["text"],
                     font=(FONT_FAMILY, 20, "bold"))
    style.configure("StatValueSmall.TLabel", background=COLORS["surface"], foreground=COLORS["text"],
                     font=(FONT_FAMILY, 13, "bold"))
    style.configure("StatCaption.TLabel", background=COLORS["surface"], foreground=COLORS["text_muted"],
                     font=(FONT_FAMILY, 9))

    style.configure("TButton", background=COLORS["surface"], foreground=COLORS["text"],
                     bordercolor=COLORS["border"], focusthickness=0, padding=(12, 6))
    style.map("TButton", background=[("active", COLORS["accent_soft"])])

    style.configure("Accent.TButton", background=COLORS["accent"], foreground="#ffffff",
                     bordercolor=COLORS["accent"], focusthickness=0, padding=(12, 6))
    style.map("Accent.TButton", background=[("active", COLORS["accent_text"]), ("!disabled", COLORS["accent"])])

    style.configure("Danger.TButton", background=COLORS["surface"], foreground=COLORS["danger"],
                     bordercolor=COLORS["danger"], focusthickness=0, padding=(12, 6))
    style.map("Danger.TButton", background=[("active", COLORS["danger_soft"])])

    style.configure("TNotebook", background=COLORS["bg"], bordercolor=COLORS["bg"])
    style.configure("TNotebook.Tab", background=COLORS["bg"], foreground=COLORS["text_muted"],
                     padding=(14, 8), font=(FONT_FAMILY, 10))
    style.map("TNotebook.Tab",
              background=[("selected", COLORS["surface"])],
              foreground=[("selected", COLORS["accent_text"])])

    style.configure("Treeview", background=COLORS["surface"], fieldbackground=COLORS["surface"],
                     foreground=COLORS["text"], bordercolor=COLORS["border"], borderwidth=1,
                     rowheight=30, font=(FONT_FAMILY, 10))
    style.configure("Treeview.Heading", background=COLORS["bg"], foreground=COLORS["text_muted"],
                     font=(FONT_FAMILY, 9, "bold"), relief="flat")
    style.map("Treeview.Heading", background=[("active", COLORS["bg"])])
    style.map("Treeview", background=[("selected", COLORS["accent_soft"])],
              foreground=[("selected", COLORS["text"])])

    style.configure("TCombobox", fieldbackground=COLORS["surface"], background=COLORS["surface"])
    style.configure("TEntry", fieldbackground=COLORS["surface"], bordercolor=COLORS["border"])


def _get_work_area():
    """Returns (left, top, right, bottom) of the desktop work area -- the
    screen minus the taskbar -- so the Focus Session HUD can sit right
    above the taskbar instead of guessing a fixed margin that could be
    wrong for a resized, relocated, or auto-hidden taskbar. Windows-only
    (uses SystemParametersInfo's SPI_GETWORKAREA); returns None elsewhere
    so the caller falls back to a fixed margin."""
    if sys.platform != "win32":
        return None
    import ctypes

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long), ("top", ctypes.c_long),
            ("right", ctypes.c_long), ("bottom", ctypes.c_long),
        ]

    SPI_GETWORKAREA = 0x0030
    rect = RECT()
    ok = ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    if not ok:
        return None
    return (rect.left, rect.top, rect.right, rect.bottom)


class FocusHud(tk.Toplevel):
    """A small always-on-top box pinned to the bottom-left of the screen,
    visible only while a Focus Session is running, so you can check the
    remaining time or pause/resume without switching to (or restoring from
    the tray) the main window.

    Deliberately a plain, un-transient Toplevel rather than a dialog owned
    by the main window: it needs to float above everything and stay
    visible even while the main window is withdrawn to the tray, which a
    transient child window would not do.
    """

    MARGIN = 16
    FALLBACK_BOTTOM_MARGIN = 56  # used only if _get_work_area() isn't available

    def __init__(self, master, on_toggle_pause):
        super().__init__(master)
        self.on_toggle_pause = on_toggle_pause

        self.overrideredirect(True)  # no title bar / OS window chrome
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.97)
        except tk.TclError:
            pass  # not supported on every platform -- purely cosmetic

        self.configure(bg=COLORS["border"])  # 1px "border" showing around the card below

        card = tk.Frame(self, bg=COLORS["surface"])
        card.pack(padx=1, pady=1)  # the bg showing through this 1px gap is the border

        inner = tk.Frame(card, bg=COLORS["surface"])
        inner.pack(padx=14, pady=12)

        tk.Label(inner, text="FOCUS SESSION", bg=COLORS["surface"], fg=COLORS["text_muted"],
                 font=(FONT_FAMILY, 8, "bold")).pack(anchor="w")

        self.time_var = tk.StringVar(value=format_duration(0))
        tk.Label(inner, textvariable=self.time_var, bg=COLORS["surface"], fg=COLORS["text"],
                 font=(FONT_FAMILY, 15, "bold")).pack(anchor="w", pady=(2, 8))

        self.pause_btn = tk.Button(
            inner, text="Pause", command=self._on_click, relief="flat", bd=0,
            bg=COLORS["accent"], fg="#ffffff", activebackground=COLORS["accent_text"],
            activeforeground="#ffffff", font=(FONT_FAMILY, 9, "bold"),
            padx=10, pady=4, cursor="hand2",
        )
        self.pause_btn.pack(fill="x")

        self.withdraw()  # hidden until a session is actually running

    def _on_click(self):
        self.on_toggle_pause()

    def update_state(self, remaining_seconds, paused):
        self.time_var.set(format_duration(remaining_seconds))
        self.pause_btn.config(text="Resume" if paused else "Pause")

    def show_at_bottom_left(self):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()

        work_area = _get_work_area()
        if work_area:
            left, _top, _right, bottom = work_area
            x, y = left + self.MARGIN, bottom - h - self.MARGIN
        else:
            x = self.MARGIN
            y = self.winfo_screenheight() - h - self.FALLBACK_BOTTOM_MARGIN

        self.geometry(f"{w}x{h}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)  # re-assert -- some WMs drop this on deiconify

    def hide(self):
        self.withdraw()


def format_duration(duration_seconds: int) -> str:
    hours, remainder = divmod(int(duration_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}h {minutes:02d}m {seconds:02d}s"


def _make_tray_image() -> Image.Image:
    """Draws a simple clock-face icon so the app doesn't need a bundled
    .ico/.png asset."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((2, 2, size - 2, size - 2), fill=(43, 108, 176, 255))
    cx, cy = size // 2, size // 2
    draw.line((cx, cy, cx, cy - 20), fill="white", width=4)
    draw.line((cx, cy, cx + 14, cy + 6), fill="white", width=4)
    return img


class ScrollableChecklist(ttk.Frame):
    """A vertically-scrolling list of checkboxes. Tkinter has no built-in
    scrollable checklist widget, so this composes a Canvas + Scrollbar +
    inner Frame, with one row (Checkbutton + optional "forget" button) per
    item, each backed by a tk.BooleanVar.

    Used by the Focus tab to show previously-used apps/domains so they can
    be picked with a click instead of retyped every time.
    """

    def __init__(self, parent, height=140, on_forget=None):
        super().__init__(parent)
        self.on_forget = on_forget

        # tk.Canvas is a raw Tk widget, not ttk -- it doesn't pick up the
        # ttk theme automatically, so without this it stays classic Tk gray
        # instead of blending into the surrounding themed frame.
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0, background=COLORS["bg"])
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self._window, width=e.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self._vars = {}
        self._rows = {}

    def _add_row(self, name, checked):
        row = ttk.Frame(self.inner)
        row.pack(fill="x", anchor="w")
        var = tk.BooleanVar(value=checked)
        ttk.Checkbutton(row, text=name, variable=var).pack(side="left", anchor="w", padx=4, pady=1)
        if self.on_forget:
            ttk.Button(row, text="✕", width=2, command=lambda: self.on_forget(name)).pack(side="right", padx=2)
        self._vars[name] = var
        self._rows[name] = row

    def set_items(self, items, checked_defaults=()):
        """Rebuilds the list from `items` (names). Any item that was already
        checked stays checked; anything newly appearing is checked only if
        it's in `checked_defaults`."""
        preserved = {name for name, var in self._vars.items() if var.get()}
        for row in self._rows.values():
            row.destroy()
        self._vars = {}
        self._rows = {}
        for name in items:
            self._add_row(name, checked=(name in preserved or name in checked_defaults))

    def add_item(self, name, checked=True):
        if name in self._vars:
            self._vars[name].set(checked)
            return
        self._add_row(name, checked)

    def remove_item(self, name):
        row = self._rows.pop(name, None)
        if row is not None:
            row.destroy()
        self._vars.pop(name, None)

    def get_checked(self):
        return [name for name, var in self._vars.items() if var.get()]


class NarrowgateApp:
    def __init__(self, db, service, warning_queue: "queue.Queue", focus_session):
        self.db = db
        self.service = service
        self.warning_queue = warning_queue
        self.focus_session = focus_session
        self._focus_was_active = False
        self._tray_queue = queue.Queue()
        self._tray_icon = None

        self.root = tk.Tk()
        self.root.title("Narrowgate")
        self.root.geometry("720x560")
        self.root.minsize(640, 480)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_button)
        _configure_style(self.root)

        self.focus_hud = FocusHud(self.root, on_toggle_pause=self._toggle_focus_pause)

        self._build_widgets()
        self._refresh_today()
        self._refresh_history_dates()
        self._refresh_limits()
        self._refresh_focus_history()
        self._refresh_focus_status()

        self.root.after(500, self._poll_queues)

    # --- layout -------------------------------------------------------

    def _build_widgets(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        self.status_var = tk.StringVar(value="Tracking: running")
        ttk.Label(top, textvariable=self.status_var).pack(side="left")

        # Quit fully ends the process (no tray icon left behind); the
        # window's own X button intentionally does something different --
        # it minimizes to the tray instead (see _on_close_button) -- so
        # this is the one control that actually stops Narrowgate running
        # in the background.
        self.quit_btn = ttk.Button(top, text="Quit App", style="Danger.TButton", command=self._confirm_quit)
        self.quit_btn.pack(side="right")

        self.toggle_btn = ttk.Button(top, text="Pause", command=self._toggle_tracking)
        self.toggle_btn.pack(side="right", padx=(0, 8))

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.today_tab = ttk.Frame(notebook)
        self.history_tab = ttk.Frame(notebook)
        self.limits_tab = ttk.Frame(notebook)
        self.focus_tab = ttk.Frame(notebook)
        notebook.add(self.today_tab, text="Today")
        notebook.add(self.history_tab, text="History")
        notebook.add(self.limits_tab, text="Limits")
        notebook.add(self.focus_tab, text="Focus")

        self._build_today_tab()
        self._build_history_tab()
        self._build_limits_tab()
        self._build_focus_tab()

    def _build_activity_tree(self, parent, height=10):
        """Shared factory for the Today/History tabs' target list: a flat
        name/type/time table (rather than the tree-with-icon-column look
        ttk.Treeview defaults to) with alternating row tints configured via
        tags -- ttk.Style can't do zebra striping on its own, so _fill_tree
        applies "evenrow"/"oddrow" tags per inserted row -- plus a scrollbar
        so a long list doesn't just get silently clipped at `height` rows.
        Packs itself into `parent`; returns the Treeview."""
        wrapper = ttk.Frame(parent, style="Card.TFrame")
        wrapper.pack(fill="both", expand=True)

        columns = ("name", "type", "time")
        tree = ttk.Treeview(wrapper, columns=columns, show="headings", height=height)
        tree.heading("name", text="Target")
        tree.heading("type", text="Type")
        tree.heading("time", text="Time Spent")
        tree.column("name", width=280, anchor="w")
        tree.column("type", width=100, anchor="center")
        tree.column("time", width=140, anchor="center")
        tree.tag_configure("evenrow", background=COLORS["surface"])
        tree.tag_configure("oddrow", background=COLORS["stripe"])

        scrollbar = ttk.Scrollbar(wrapper, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return tree

    def _build_stat_card(self, parent, title, value_var, value_style="StatValue.TLabel", wraplength=None):
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        value_label = ttk.Label(card, textvariable=value_var, style=value_style, justify="left")
        if wraplength:
            value_label.configure(wraplength=wraplength)
        value_label.pack(anchor="w", fill="x")
        ttk.Label(card, text=title, style="StatCaption.TLabel").pack(anchor="w", pady=(4, 0))
        return card

    def _build_today_tab(self):
        container = ttk.Frame(self.today_tab, padding=16)
        container.pack(fill="both", expand=True)

        # --- Summary stat cards ---------------------------------------
        self.stat_total_var = tk.StringVar(value=format_duration(0))
        self.stat_top_var = tk.StringVar(value="—")
        self.stat_count_var = tk.StringVar(value="0")

        stats_row = ttk.Frame(container)
        stats_row.pack(fill="x", pady=(0, 12))

        self._build_stat_card(stats_row, "Total time today", self.stat_total_var).pack(
            side="left", fill="both", expand=True, padx=(0, 8))
        self._build_stat_card(
            stats_row, "Top app / site", self.stat_top_var,
            value_style="StatValueSmall.TLabel", wraplength=170,
        ).pack(side="left", fill="both", expand=True, padx=8)
        self._build_stat_card(stats_row, "Tracked today", self.stat_count_var).pack(
            side="left", fill="both", expand=True, padx=(8, 0))

        # --- Activity list card -----------------------------------------
        list_card = ttk.Frame(container, style="Card.TFrame", padding=12)
        list_card.pack(fill="both", expand=True)

        header_row = ttk.Frame(list_card, style="Card.TFrame")
        header_row.pack(fill="x", pady=(0, 8))
        ttk.Label(header_row, text="Today's activity", style="Card.TLabel",
                  font=(FONT_FAMILY, 11, "bold")).pack(side="left")
        ttk.Button(header_row, text="Refresh", style="Accent.TButton",
                   command=self._refresh_today).pack(side="right")

        self.today_tree = self._build_activity_tree(list_card)

    def _build_history_tab(self):
        controls = ttk.Frame(self.history_tab)
        controls.pack(fill="x", padx=8, pady=8)

        ttk.Label(controls, text="Date:").pack(side="left")
        self.history_date_var = tk.StringVar()
        self.history_date_combo = ttk.Combobox(controls, textvariable=self.history_date_var, state="readonly")
        self.history_date_combo.pack(side="left", padx=8)
        self.history_date_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_history())

        ttk.Button(controls, text="Refresh dates", command=self._refresh_history_dates).pack(side="left")

        tree_area = ttk.Frame(self.history_tab, padding=(8, 0, 8, 8))
        tree_area.pack(fill="both", expand=True)
        self.history_tree = self._build_activity_tree(tree_area)

    def _build_limits_tab(self):
        columns = ("limit",)
        self.limits_tree = ttk.Treeview(self.limits_tab, columns=columns, show="tree headings")
        self.limits_tree.heading("#0", text="Target")
        self.limits_tree.heading("limit", text="Daily Limit")
        self.limits_tree.column("#0", width=260)
        self.limits_tree.column("limit", width=160, anchor="center")
        self.limits_tree.pack(fill="both", expand=True, padx=8, pady=8)

        btns = ttk.Frame(self.limits_tab)
        btns.pack(pady=(0, 8))
        ttk.Button(btns, text="Add", command=self._add_limit).pack(side="left", padx=4)
        ttk.Button(btns, text="Edit", command=self._edit_limit).pack(side="left", padx=4)
        ttk.Button(btns, text="Delete", command=self._delete_limit).pack(side="left", padx=4)

    def _build_focus_tab(self):
        intro = ttk.Label(
            self.focus_tab,
            text="Close everything except an allowed list of apps/websites, for a set amount of time.",
            wraplength=600, justify="left",
        )
        intro.pack(fill="x", padx=8, pady=(8, 0))

        top = ttk.Frame(self.focus_tab, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Duration (minutes):").pack(side="left")
        self.focus_duration_var = tk.StringVar(value="60")
        ttk.Entry(top, textvariable=self.focus_duration_var, width=6).pack(side="left", padx=(4, 16))
        self.focus_status_var = tk.StringVar(value="No Focus Session running")
        ttk.Label(top, textvariable=self.focus_status_var).pack(side="left")

        lists_frame = ttk.Frame(self.focus_tab)
        lists_frame.pack(fill="both", expand=True, padx=8, pady=4)

        apps_frame = ttk.LabelFrame(lists_frame, text="Allowed apps (process name, e.g. code.exe)")
        apps_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.focus_apps_checklist = ScrollableChecklist(
            apps_frame, height=140, on_forget=lambda name: self._forget_focus_history(name, "APP")
        )
        self.focus_apps_checklist.pack(fill="both", expand=True, padx=4, pady=4)
        apps_row = ttk.Frame(apps_frame)
        apps_row.pack(fill="x", padx=4, pady=(0, 4))
        self.focus_app_entry_var = tk.StringVar()
        app_entry = ttk.Entry(apps_row, textvariable=self.focus_app_entry_var)
        app_entry.pack(side="left", fill="x", expand=True)
        app_entry.bind("<Return>", lambda e: self._add_focus_app())
        ttk.Button(apps_row, text="Add", command=self._add_focus_app).pack(side="left", padx=(4, 0))

        domains_frame = ttk.LabelFrame(lists_frame, text="Allowed websites (domain, e.g. docs.google.com)")
        domains_frame.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.focus_domains_checklist = ScrollableChecklist(
            domains_frame, height=140, on_forget=lambda name: self._forget_focus_history(name, "DOMAIN")
        )
        self.focus_domains_checklist.pack(fill="both", expand=True, padx=4, pady=4)
        domains_row = ttk.Frame(domains_frame)
        domains_row.pack(fill="x", padx=4, pady=(0, 4))
        self.focus_domain_entry_var = tk.StringVar()
        domain_entry = ttk.Entry(domains_row, textvariable=self.focus_domain_entry_var)
        domain_entry.pack(side="left", fill="x", expand=True)
        domain_entry.bind("<Return>", lambda e: self._add_focus_domain())
        ttk.Button(domains_row, text="Add", command=self._add_focus_domain).pack(side="left", padx=(4, 0))

        hint = ttk.Label(
            self.focus_tab,
            text="Check the ones you want for this session. Typing a new one adds and checks it, "
                 "and it's remembered for next time -- click ✕ to forget an entry for good.",
            wraplength=600, justify="left", foreground="#666",
        )
        hint.pack(fill="x", padx=8, pady=(0, 4))

        btn_row = ttk.Frame(self.focus_tab)
        btn_row.pack(pady=(0, 8))
        self.focus_toggle_btn = ttk.Button(
            btn_row, text="Start Focus Session", style="Accent.TButton", command=self._toggle_focus_session
        )
        self.focus_toggle_btn.pack(side="left", padx=(0, 8))
        self.focus_pause_btn = ttk.Button(
            btn_row, text="Pause", command=self._toggle_focus_pause, state="disabled"
        )
        self.focus_pause_btn.pack(side="left")

        hud_hint = ttk.Label(
            self.focus_tab,
            text="A small floating box in the bottom-left of your screen also lets you pause/resume "
                 "without switching back to this window.",
            wraplength=600, justify="left", foreground=COLORS["text_muted"],
        )
        hud_hint.pack(fill="x", padx=8, pady=(0, 8))

    # --- data refresh ---------------------------------------------------

    def _fill_tree(self, tree, rows):
        tree.delete(*tree.get_children())
        for i, (target_name, target_type, duration_seconds) in enumerate(rows):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            tree.insert(
                "", "end",
                values=(target_name, target_type.title(), format_duration(duration_seconds)),
                tags=(tag,),
            )

    def _refresh_today(self):
        rows = self.db.get_daily_summary()
        self._fill_tree(self.today_tree, rows)
        self._update_today_stats(rows)
        self.status_var.set(
            f"Tracking: {'running' if self.service.is_running() else 'paused'}"
        )
        self.root.after(2000, self._refresh_today)

    def _update_today_stats(self, rows):
        """rows is already ORDER BY duration_seconds DESC (see
        TimeTrackerDB.get_daily_summary), so rows[0] is the top target."""
        total_seconds = sum(duration for _, _, duration in rows)
        self.stat_total_var.set(format_duration(total_seconds))
        if rows:
            top_name, _, top_seconds = rows[0]
            self.stat_top_var.set(f"{top_name}\n{format_duration(top_seconds)}")
        else:
            self.stat_top_var.set("—")
        self.stat_count_var.set(str(len(rows)))

    def _refresh_history_dates(self):
        dates = self.db.get_all_dates()
        self.history_date_combo["values"] = dates
        if dates and not self.history_date_var.get():
            self.history_date_var.set(dates[0])
        self._refresh_history()

    def _refresh_history(self):
        selected_date = self.history_date_var.get() or None
        self._fill_tree(self.history_tree, self.db.get_daily_summary(selected_date))

    def _refresh_limits(self):
        self.limits_tree.delete(*self.limits_tree.get_children())
        for target_name, limit_seconds in sorted(self.db.get_limits().items()):
            self.limits_tree.insert("", "end", text=target_name, values=(format_duration(limit_seconds),))

    # --- limits editing ---------------------------------------------------

    def _prompt_limit(self, initial_name="", initial_minutes=""):
        """Small modal form for target name + limit (in minutes). Returns
        (name, minutes) or None if cancelled."""
        result = {}

        dialog = tk.Toplevel(self.root)
        dialog.title("Limit")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="Target (process name or domain):").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        name_var = tk.StringVar(value=initial_name)
        name_entry = ttk.Entry(dialog, textvariable=name_var, width=32)
        name_entry.grid(row=1, column=0, padx=8, pady=(0, 8))

        ttk.Label(dialog, text="Daily limit (minutes):").grid(row=2, column=0, sticky="w", padx=8, pady=(0, 2))
        minutes_var = tk.StringVar(value=str(initial_minutes))
        minutes_entry = ttk.Entry(dialog, textvariable=minutes_var, width=32)
        minutes_entry.grid(row=3, column=0, padx=8, pady=(0, 8))

        def on_ok():
            name = name_var.get().strip()
            try:
                minutes = float(minutes_var.get().strip())
            except ValueError:
                messagebox.showerror("Invalid limit", "Enter the limit as a number of minutes.", parent=dialog)
                return
            if not name or minutes <= 0:
                messagebox.showerror("Invalid limit", "Enter a target name and a limit greater than 0.", parent=dialog)
                return
            result["name"] = name
            result["minutes"] = minutes
            dialog.destroy()

        btns = ttk.Frame(dialog)
        btns.grid(row=4, column=0, pady=(0, 8))
        ttk.Button(btns, text="Save", command=on_ok).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=dialog.destroy).pack(side="left", padx=4)

        name_entry.focus_set()
        dialog.wait_window()
        return result or None

    def _add_limit(self):
        result = self._prompt_limit()
        if not result:
            return
        self.db.set_limit(result["name"], int(result["minutes"] * 60))
        self._refresh_limits()

    def _selected_limit_target(self):
        selection = self.limits_tree.selection()
        if not selection:
            messagebox.showinfo("No selection", "Select a limit first.")
            return None
        return self.limits_tree.item(selection[0], "text")

    def _edit_limit(self):
        target_name = self._selected_limit_target()
        if not target_name:
            return
        current_seconds = self.db.get_limits().get(target_name, 0)
        result = self._prompt_limit(initial_name=target_name, initial_minutes=round(current_seconds / 60, 2))
        if not result:
            return
        # Renaming a target: drop the old key so it doesn't linger with a stale limit.
        if result["name"].strip().lower() != target_name:
            self.db.delete_limit(target_name)
        self.db.set_limit(result["name"], int(result["minutes"] * 60))
        self._refresh_limits()

    def _delete_limit(self):
        target_name = self._selected_limit_target()
        if not target_name:
            return
        if messagebox.askyesno("Delete limit", f"Remove the daily limit for '{target_name}'?"):
            self.db.delete_limit(target_name)
            self._refresh_limits()

    # --- Focus Session ------------------------------------------------------

    def _add_focus_app(self):
        val = self.focus_app_entry_var.get().strip().lower()
        if val:
            self.db.add_focus_history(val, "APP")
            self.focus_apps_checklist.add_item(val, checked=True)
        self.focus_app_entry_var.set("")

    def _add_focus_domain(self):
        val = self.focus_domain_entry_var.get().strip().lower()
        if val.startswith("www."):
            val = val[4:]
        if val:
            self.db.add_focus_history(val, "DOMAIN")
            self.focus_domains_checklist.add_item(val, checked=True)
        self.focus_domain_entry_var.set("")

    def _forget_focus_history(self, name, kind):
        self.db.delete_focus_history(name, kind)
        if kind == "APP":
            self.focus_apps_checklist.remove_item(name)
        else:
            self.focus_domains_checklist.remove_item(name)

    def _refresh_focus_history(self):
        """Populates the checklists from everything ever added, most
        recently used first. Safe to call any time (e.g. if another part
        of the app ever adds history entries) since set_items() preserves
        whatever is currently checked."""
        self.focus_apps_checklist.set_items(self.db.get_focus_history("APP"))
        self.focus_domains_checklist.set_items(self.db.get_focus_history("DOMAIN"))

    def _toggle_focus_session(self):
        if self.focus_session.is_active:
            self.focus_session.stop()
            self._update_focus_widgets()
            self._update_focus_hud()
            return

        try:
            minutes = float(self.focus_duration_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid duration", "Enter the duration as a number of minutes.")
            return
        if minutes <= 0:
            messagebox.showerror("Invalid duration", "Duration must be greater than 0.")
            return

        apps = self.focus_apps_checklist.get_checked()
        domains = self.focus_domains_checklist.get_checked()
        if not apps and not domains:
            if not messagebox.askyesno(
                "No allowed targets",
                "You haven't allowed any apps or websites -- this will close nearly everything "
                "you switch to. Start anyway?",
            ):
                return

        # Bump last_used for whatever's checked so it sorts to the top of
        # the checklist next time the app is opened.
        for app in apps:
            self.db.add_focus_history(app, "APP")
        for domain in domains:
            self.db.add_focus_history(domain, "DOMAIN")

        self.focus_session.start(minutes, apps, domains)
        self._update_focus_widgets()
        self._update_focus_hud()

    def _toggle_focus_pause(self):
        """Shared by the Focus tab's Pause/Resume button and the floating
        HUD's button -- both just flip the same FocusSession."""
        if not self.focus_session.is_active:
            return
        if self.focus_session.is_paused:
            self.focus_session.resume()
        else:
            self.focus_session.pause()
        self._update_focus_widgets()
        self._update_focus_hud()

    def _update_focus_widgets(self):
        if self.focus_session.is_active:
            remaining = self.focus_session.remaining_seconds()
            if self.focus_session.is_paused:
                self.focus_status_var.set(f"Focus Session paused — {format_duration(remaining)} remaining")
                self.focus_pause_btn.config(text="Resume")
            else:
                self.focus_status_var.set(f"Focus Session active — {format_duration(remaining)} remaining")
                self.focus_pause_btn.config(text="Pause")
            self.focus_toggle_btn.config(text="Stop Focus Session")
            self.focus_pause_btn.config(state="normal")
        else:
            self.focus_status_var.set("No Focus Session running")
            self.focus_toggle_btn.config(text="Start Focus Session")
            self.focus_pause_btn.config(text="Pause", state="disabled")

    def _update_focus_hud(self):
        if self.focus_session.is_active:
            self.focus_hud.update_state(self.focus_session.remaining_seconds(), self.focus_session.is_paused)
            self.focus_hud.show_at_bottom_left()
        else:
            self.focus_hud.hide()

    def _refresh_focus_status(self):
        active = self.focus_session.is_active
        if self._focus_was_active and not active:
            self._show_warning_popup("Focus Session", "Your Focus Session has ended.", "focus")
        self._focus_was_active = active
        self._update_focus_widgets()
        self._update_focus_hud()
        self.root.after(1000, self._refresh_focus_status)

    # --- tracking control -------------------------------------------------

    def _toggle_tracking(self):
        if self.service.is_running():
            self.service.stop()
            self.toggle_btn.config(text="Resume")
        else:
            self.service.start()
            self.toggle_btn.config(text="Pause")
        self.status_var.set(f"Tracking: {'running' if self.service.is_running() else 'paused'}")

    # --- warnings / tray --------------------------------------------------

    def _poll_queues(self):
        while True:
            try:
                title, message, level = self.warning_queue.get_nowait()
            except queue.Empty:
                break
            self._show_warning_popup(title, message, level)

        while True:
            try:
                command = self._tray_queue.get_nowait()
            except queue.Empty:
                break
            if command == "show":
                self._show_window()
            elif command == "quit":
                self._shutdown()
                return  # don't reschedule after a shutdown

        self.root.after(500, self._poll_queues)

    def _show_warning_popup(self, title, message, level):
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.attributes("-topmost", True)
        frame = ttk.Frame(popup, padding=16)
        frame.pack()
        ttk.Label(frame, text=message, wraplength=320, justify="left").pack(pady=(0, 12))
        ttk.Button(frame, text="OK", command=popup.destroy).pack()
        # Auto-dismiss the informational 80% warning so it doesn't pile up
        # if you're away from the keyboard; breach popups stay until closed.
        if level == "warning":
            popup.after(8000, popup.destroy)

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _on_close_button(self):
        # Minimize to tray instead of exiting, since the tracker should
        # keep running in the background.
        self.root.withdraw()

    def _confirm_quit(self):
        message = "This closes Narrowgate completely -- tracking stops and it won't keep running in the background."
        if self.focus_session.is_active:
            message += " Your current Focus Session will end too."
        if messagebox.askyesno("Quit Narrowgate", message + "\n\nQuit anyway?"):
            self._shutdown()

    def _build_tray_icon(self):
        menu = pystray.Menu(
            pystray.MenuItem("Open Dashboard", lambda: self._tray_queue.put("show"), default=True),
            pystray.MenuItem("Quit", lambda: self._tray_queue.put("quit")),
        )
        self._tray_icon = pystray.Icon("Narrowgate", _make_tray_image(), "Narrowgate", menu)
        self._tray_icon.run()

    def _shutdown(self):
        self.service.stop()
        if self._tray_icon:
            self._tray_icon.stop()
        self.root.destroy()

    def run(self):
        tray_thread = threading.Thread(target=self._build_tray_icon, daemon=True)
        tray_thread.start()
        self.root.mainloop()
