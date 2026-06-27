"""LoL Auto-Pick — accepts your queue, bans/picks champions and pings you in-game.

A themed companion that talks to the local League client (see lcu.py). While
armed it:

  1. Accepts the ready-check as soon as a match is found.
  2. In champion select, bans and picks from your priority lists, always taking
     the highest-priority champion that is still available.
  3. Raises the window and plays a sound the moment the game launches.

Ban safety rules: never ban a champion on your own pick list, and never ban one
an ally is hovering. The full champion list and portraits are loaded live from
the client, so they always match the current patch.

Only client convenience is automated (no in-game scripting). Any client
automation is technically against Riot's Terms of Service — use at your own
risk. See README.md.
"""

import io
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import requests
from PIL import Image, ImageDraw, ImageTk

from lcu import LCU, _normalize

MAX_PICKS = 5
MAX_BANS = 3
POLL_SECONDS = 1.0
THUMB = 34
CONFIG_PATH = Path.home() / ".lol_autopick.json"

# --- Hextech-ish dark palette --------------------------------------------- #
WIN_BG = "#0A1428"
PANEL = "#0F1E2E"
ROW = "#13283A"
HOVER = "#1B3B52"
BORDER = "#1E3543"
SEARCH_BG = "#1C3145"
OFF_TRACK = "#2A3A4D"
GOLD = "#C8AA6E"
GOLD_DIM = "#7A6740"
TEXT = "#F0E6D2"
MUTED = "#8A94A6"
TEAL = "#0AC8B9"
DANGER = "#C0413B"


def build_theme(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=WIN_BG, foreground=TEXT, borderwidth=0)
    style.configure("Win.TFrame", background=WIN_BG)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("Title.TLabel", background=WIN_BG, foreground=GOLD,
                    font=("Segoe UI Semibold", 18))
    style.configure("Sub.TLabel", background=WIN_BG, foreground=MUTED,
                    font=("Segoe UI", 9))
    style.configure("Head.TLabel", background=PANEL, foreground=GOLD,
                    font=("Segoe UI Semibold", 11))
    style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
    style.configure("Muted.TLabel", background=PANEL, foreground=MUTED,
                    font=("Segoe UI", 9))
    style.configure("Pill.TLabel", background=ROW, foreground=MUTED,
                    font=("Segoe UI Semibold", 9), padding=(10, 4))

    style.configure("TCheckbutton", background=WIN_BG, foreground=TEXT)
    style.map("TCheckbutton", background=[("active", WIN_BG)],
              foreground=[("active", GOLD)])

    style.configure("Search.TEntry", fieldbackground=ROW, foreground=TEXT,
                    insertcolor=GOLD, bordercolor=BORDER, padding=6)

    # Segmented add-target toggle.
    style.configure("Seg.TButton", background=ROW, foreground=MUTED,
                    font=("Segoe UI Semibold", 9), borderwidth=0, padding=(12, 5))
    style.map("Seg.TButton", background=[("active", HOVER)])
    style.configure("SegOn.TButton", background=GOLD, foreground=WIN_BG,
                    font=("Segoe UI Semibold", 9), borderwidth=0, padding=(12, 5))
    style.map("SegOn.TButton", background=[("active", GOLD)])

    # Primary start/stop button.
    style.configure("Start.TButton", background=GOLD, foreground=WIN_BG,
                    font=("Segoe UI Semibold", 12), borderwidth=0, padding=(18, 9))
    style.map("Start.TButton", background=[("active", "#D7BD86")])
    style.configure("Stop.TButton", background=DANGER, foreground=TEXT,
                    font=("Segoe UI Semibold", 12), borderwidth=0, padding=(18, 9))
    style.map("Stop.TButton", background=[("active", "#D45B55")])

    style.configure("Vertical.TScrollbar", background=ROW, troughcolor=PANEL,
                    bordercolor=PANEL, arrowcolor=MUTED)
    return style


class Switch(tk.Frame):
    """A small rounded on/off toggle with a label, drawn on a canvas."""

    W, H = 46, 24

    def __init__(self, master, text, value=True, command=None):
        super().__init__(master, bg=WIN_BG)
        self._value = bool(value)
        self._command = command
        self.canvas = tk.Canvas(self, width=self.W, height=self.H, bg=WIN_BG,
                                highlightthickness=0, cursor="hand2")
        self.canvas.pack(side="left")
        self.label = tk.Label(self, text=text, bg=WIN_BG, fg=TEXT,
                              font=("Segoe UI", 10), cursor="hand2")
        self.label.pack(side="left", padx=(10, 0))
        for w in (self.canvas, self.label):
            w.bind("<Button-1>", self._toggle)
        self._draw()

    @property
    def value(self):
        return self._value

    def _toggle(self, _event=None):
        self._value = not self._value
        self._draw()
        if self._command:
            self._command(self._value)

    def _pill(self, x1, y1, x2, y2, color):
        r = (y2 - y1) / 2
        self.canvas.create_oval(x1, y1, x1 + 2 * r, y2, fill=color, outline="")
        self.canvas.create_oval(x2 - 2 * r, y1, x2, y2, fill=color, outline="")
        self.canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=color, outline="")

    def _draw(self):
        self.canvas.delete("all")
        self._pill(2, 4, self.W - 2, self.H - 4, GOLD if self._value else OFF_TRACK)
        kx = self.W - 13 if self._value else 13
        self.canvas.create_oval(kx - 8, 4, kx + 8, self.H - 4, fill=TEXT, outline="")


class AutoPickApp:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.icon_queue = queue.Queue()
        self.closing = threading.Event()
        self.armed = threading.Event()

        # Champion data (filled once the client connects).
        self.champs = []                  # [{id,name,alias}]
        self.by_id = {}
        self.name_to_id = {}
        self.champ_loaded = False
        self.creds = None

        # Priority lists (the source of truth the worker reads).
        self.pick_ids = []
        self.ban_ids = []

        # Icon handling.
        self.icon_cache = {}              # id -> PhotoImage
        self.icon_requested = set()
        self.icon_widgets = {}            # id -> [Label,...]

        self.auto_accept_on = True
        self.auto_ban_on = True
        self.target_var = tk.StringVar(value="pick")
        self.search_var = tk.StringVar()

        self.pending = self._load_config()

        build_theme(root)
        self.placeholder = self._make_placeholder()
        self._build_ui()
        self._render_results()
        self._render_lists()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self._service, daemon=True).start()
        threading.Thread(target=self._icon_worker, daemon=True).start()
        self._drain_events()

    # ------------------------------------------------------------------ UI -- #
    def _build_ui(self):
        self.root.title("LoL Auto-Pick")
        self.root.configure(bg=WIN_BG)
        self.root.minsize(760, 560)

        # Header.
        header = ttk.Frame(self.root, style="Win.TFrame", padding=(18, 14, 18, 8))
        header.pack(fill="x")
        ttk.Label(header, text="LoL Auto-Pick", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="Queue · Ban · Pick", style="Sub.TLabel").pack(
            side="left", padx=(10, 0), pady=(8, 0))
        self.pill = ttk.Label(header, text="getrennt", style="Pill.TLabel")
        self.pill.pack(side="right")

        body = ttk.Frame(self.root, style="Win.TFrame", padding=(18, 6, 18, 6))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1, uniform="col")
        body.columnconfigure(1, weight=1, uniform="col")
        body.rowconfigure(0, weight=1)

        self._build_picker(body)
        self._build_lists(body)
        self._build_footer()

    def _card(self, parent, title):
        card = ttk.Frame(parent, style="Panel.TFrame", padding=12)
        head = ttk.Frame(card, style="Panel.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text=title, style="Head.TLabel").pack(side="left")
        return card, head

    def _build_picker(self, parent):
        card, head = self._card(parent, "Champion suchen")
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        # Add-target toggle on the right of the header.
        seg = ttk.Frame(head, style="Panel.TFrame")
        seg.pack(side="right")
        self.seg_pick = ttk.Button(seg, text="→ Picks", style="SegOn.TButton",
                                   command=lambda: self._set_target("pick"))
        self.seg_pick.pack(side="left", padx=(0, 4))
        self.seg_ban = ttk.Button(seg, text="→ Bans", style="Seg.TButton",
                                  command=lambda: self._set_target("ban"))
        self.seg_ban.pack(side="left")

        ttk.Label(card, text="Tippen zum Suchen · klicken zum Hinzufügen",
                  style="Muted.TLabel").pack(anchor="w", pady=(8, 4))
        search = tk.Frame(card, bg=SEARCH_BG, highlightthickness=1,
                          highlightbackground=GOLD_DIM, highlightcolor=GOLD)
        search.pack(fill="x", pady=(0, 8))
        tk.Label(search, text="🔎", bg=SEARCH_BG, fg=GOLD,
                 font=("Segoe UI", 11)).pack(side="left", padx=(8, 2))
        entry = tk.Entry(search, textvariable=self.search_var, bd=0, relief="flat",
                         bg=SEARCH_BG, fg=TEXT, insertbackground=GOLD,
                         font=("Segoe UI", 12))
        entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(2, 8))
        self.search_entry = entry
        self.search_var.trace_add("write", lambda *_: self._render_results())
        self.root.after(150, entry.focus_set)      # ready to type right away

        # Scrollable results.
        wrap = tk.Frame(card, bg=PANEL)
        wrap.pack(fill="both", expand=True)
        self.results_canvas = tk.Canvas(wrap, bg=PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.results_canvas.yview)
        self.results_inner = tk.Frame(self.results_canvas, bg=PANEL)
        self._iid = self.results_canvas.create_window((0, 0), window=self.results_inner,
                                                       anchor="nw")
        self.results_canvas.configure(yscrollcommand=sb.set)
        self.results_canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.results_inner.bind(
            "<Configure>",
            lambda e: self.results_canvas.configure(
                scrollregion=self.results_canvas.bbox("all")))
        self.results_canvas.bind(
            "<Configure>",
            lambda e: self.results_canvas.itemconfigure(self._iid, width=e.width))
        self._bind_wheel(self.results_canvas)

    def _build_lists(self, parent):
        right = ttk.Frame(parent, style="Win.TFrame")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.rowconfigure(0, weight=3)
        right.rowconfigure(1, weight=2)
        right.columnconfigure(0, weight=1)

        pick_card, _ = self._card(right, f"Pick-Priorität (max {MAX_PICKS})")
        pick_card.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        self.pick_box = tk.Frame(pick_card, bg=PANEL)
        self.pick_box.pack(fill="both", expand=True, pady=(10, 0))

        ban_card, _ = self._card(right, f"Bann-Priorität (max {MAX_BANS})")
        ban_card.grid(row=1, column=0, sticky="nsew")
        self.ban_box = tk.Frame(ban_card, bg=PANEL)
        self.ban_box.pack(fill="both", expand=True, pady=(10, 0))

    def _build_footer(self):
        footer = ttk.Frame(self.root, style="Win.TFrame", padding=(18, 6, 18, 14))
        footer.pack(fill="x")

        opts = ttk.Frame(footer, style="Win.TFrame")
        opts.pack(side="left", anchor="w")
        self.acc_switch = Switch(opts, "Queue automatisch annehmen",
                                 value=self.pending.get("auto_accept", True),
                                 command=lambda v: self._set_opt("acc", v))
        self.acc_switch.pack(anchor="w", pady=3)
        self.ban_switch = Switch(opts, "Automatisch bannen",
                                 value=self.pending.get("auto_ban", True),
                                 command=lambda v: self._set_opt("ban", v))
        self.ban_switch.pack(anchor="w", pady=3)
        self.auto_accept_on = self.acc_switch.value
        self.auto_ban_on = self.ban_switch.value

        right = ttk.Frame(footer, style="Win.TFrame")
        right.pack(side="right", anchor="e")
        self.status_lbl = ttk.Label(right, text="Bereit.", style="Sub.TLabel")
        self.status_lbl.pack(anchor="e", pady=(0, 6))
        self.start_btn = ttk.Button(right, text="Start", style="Start.TButton",
                                    command=self._toggle_armed)
        self.start_btn.pack(anchor="e")

    # ----------------------------------------------------------- rendering -- #
    def _make_placeholder(self):
        im = Image.new("RGBA", (THUMB, THUMB), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, THUMB - 1, THUMB - 1], radius=7,
                            fill=(30, 53, 67, 255), outline=(122, 103, 64, 255))
        return ImageTk.PhotoImage(im)

    def _thumb(self, png_bytes):
        im = Image.open(io.BytesIO(png_bytes)).convert("RGBA").resize(
            (THUMB, THUMB), Image.LANCZOS)
        mask = Image.new("L", (THUMB, THUMB), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, THUMB - 1, THUMB - 1],
                                               radius=7, fill=255)
        im.putalpha(mask)
        return ImageTk.PhotoImage(im)

    def _icon_for(self, cid, label):
        """Return a cached icon (or placeholder) and register the label for updates."""
        lst = self.icon_widgets.setdefault(cid, [])
        lst[:] = [w for w in lst if self._alive(w)]   # drop destroyed rows
        lst.append(label)
        if cid in self.icon_cache:
            return self.icon_cache[cid]
        if self.creds and cid not in self.icon_requested:
            self.icon_requested.add(cid)
            self.icon_queue.put(cid)
        return self.placeholder

    @staticmethod
    def _alive(widget):
        try:
            return bool(widget) and bool(widget.winfo_exists())
        except tk.TclError:
            return False

    def _name(self, cid):
        c = self.by_id.get(cid)
        return c["name"] if c else str(cid)

    def _render_results(self):
        for w in self.results_inner.winfo_children():
            w.destroy()
        if not self.champ_loaded:
            tk.Label(self.results_inner, text="Mit dem League-Client verbinden,\n"
                     "um Champions zu laden …", bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 10), justify="left").pack(anchor="w", pady=8)
            return

        q = _normalize(self.search_var.get())
        if q:
            matches = [c for c in self.champs if q in _normalize(c["name"])
                       or q in _normalize(c["alias"])]
            matches.sort(key=lambda c: (not _normalize(c["name"]).startswith(q),
                                        c["name"]))
        else:
            matches = self.champs
        for c in matches:
            self._result_row(c)
        if not matches:
            tk.Label(self.results_inner, text="Kein Treffer.", bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 10)).pack(anchor="w", pady=8)

    def _result_row(self, champ):
        cid = champ["id"]
        row = tk.Frame(self.results_inner, bg=PANEL, cursor="hand2")
        row.pack(fill="x", pady=1)
        img = tk.Label(row, bg=PANEL)
        img.configure(image=self._icon_for(cid, img))
        img.image = self.icon_cache.get(cid, self.placeholder)
        img.pack(side="left", padx=(2, 8), pady=2)
        name = tk.Label(row, text=champ["name"], bg=PANEL, fg=TEXT,
                        font=("Segoe UI", 10), anchor="w")
        name.pack(side="left", fill="x", expand=True)

        def enter(_=None):
            for w in (row, img, name):
                w.configure(bg=HOVER)
        def leave(_=None):
            for w in (row, img, name):
                w.configure(bg=PANEL)
        for w in (row, img, name):
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
            w.bind("<Button-1>", lambda _e, i=cid: self._add(i))

    def _render_lists(self):
        self._render_one(self.pick_box, self.pick_ids, "pick")
        self._render_one(self.ban_box, self.ban_ids, "ban")

    def _render_one(self, box, ids, kind):
        for w in box.winfo_children():
            w.destroy()
        if not self.champ_loaded:
            names = self.pending.get("picks" if kind == "pick" else "bans", [])
            text = ("Gespeichert: " + ", ".join(names)) if names else \
                   "Noch leer – Champions links anklicken."
            tk.Label(box, text=text, bg=PANEL, fg=MUTED, font=("Segoe UI", 9),
                     wraplength=320, justify="left").pack(anchor="w")
            return
        if not ids:
            tk.Label(box, text="Noch leer – links einen Champion anklicken.",
                     bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
            return
        for idx, cid in enumerate(ids):
            self._list_row(box, ids, kind, idx, cid)

    def _list_row(self, box, ids, kind, idx, cid):
        row = tk.Frame(box, bg=ROW)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=str(idx + 1), bg=ROW, fg=GOLD, width=2,
                 font=("Segoe UI Semibold", 10)).pack(side="left", padx=(6, 4))
        img = tk.Label(row, bg=ROW)
        img.configure(image=self._icon_for(cid, img))
        img.image = self.icon_cache.get(cid, self.placeholder)
        img.pack(side="left", padx=(0, 8), pady=3)
        tk.Label(row, text=self._name(cid), bg=ROW, fg=TEXT, anchor="w",
                 font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True)
        for sym, fn in (("✕", lambda: self._remove(kind, cid)),
                        ("▼", lambda: self._move(kind, idx, 1)),
                        ("▲", lambda: self._move(kind, idx, -1))):
            tk.Button(row, text=sym, command=fn, bg=ROW, fg=MUTED,
                      activebackground=HOVER, activeforeground=GOLD, bd=0,
                      font=("Segoe UI", 10), cursor="hand2", width=2).pack(
                side="right", padx=1)

    # ------------------------------------------------------------- actions -- #
    def _set_target(self, target):
        self.target_var.set(target)
        self.seg_pick.configure(style="SegOn.TButton" if target == "pick" else "Seg.TButton")
        self.seg_ban.configure(style="SegOn.TButton" if target == "ban" else "Seg.TButton")

    def _add(self, cid):
        if self.target_var.get() == "pick":
            ids, limit = self.pick_ids, MAX_PICKS
        else:
            ids, limit = self.ban_ids, MAX_BANS
        if cid in ids:
            return
        if len(ids) >= limit:
            self._set_status(f"Liste voll (max {limit}).")
            return
        ids.append(cid)
        self._render_lists()
        self._save_config()

    def _remove(self, kind, cid):
        ids = self.pick_ids if kind == "pick" else self.ban_ids
        if cid in ids:
            ids.remove(cid)
            self._render_lists()
            self._save_config()

    def _move(self, kind, idx, delta):
        ids = self.pick_ids if kind == "pick" else self.ban_ids
        j = idx + delta
        if 0 <= j < len(ids):
            ids[idx], ids[j] = ids[j], ids[idx]
            self._render_lists()
            self._save_config()

    def _set_opt(self, which, value):
        if which == "acc":
            self.auto_accept_on = value
        else:
            self.auto_ban_on = value
        self._save_config()

    def _toggle_armed(self):
        if self.armed.is_set():
            self.armed.clear()
            self.start_btn.configure(text="Start", style="Start.TButton")
            self._set_status("Gestoppt.")
        else:
            if not self.pick_ids and not self.ban_ids:
                self._set_status("Erst Champions wählen.")
                return
            self.armed.set()
            self.start_btn.configure(text="Stopp", style="Stop.TButton")
            self._set_status("Aktiv – wartet auf Queue/Champ-Select.")

    def _set_status(self, text):
        self.status_lbl.configure(text=text)

    # ------------------------------------------------- worker -> GUI events -- #
    def _post(self, kind, payload=None):
        self.events.put((kind, payload))

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._set_status(payload)
                elif kind == "status":
                    state, text = payload
                    self._set_pill(state)
                    self._set_status(text)
                elif kind == "phase":
                    self._set_pill_phase(payload)
                elif kind == "creds":
                    self.creds = payload
                elif kind == "champ_data":
                    self._on_champ_data(payload)
                elif kind == "icon":
                    self._on_icon(payload)
                elif kind == "notify":
                    self._notify()
        except queue.Empty:
            pass
        self.root.after(120, self._drain_events)

    def _set_pill(self, state):
        colors = {"verbunden": (TEAL, WIN_BG), "warten": (ROW, MUTED),
                  "getrennt": (ROW, MUTED)}
        bg, fg = colors.get(state, (ROW, MUTED))
        self.pill.configure(text=state, background=bg, foreground=fg)
        style = ttk.Style(self.root)
        style.configure("Pill.TLabel", background=bg, foreground=fg)

    def _set_pill_phase(self, phase):
        if not phase or phase in ("None", "Lobby"):
            self._set_pill("verbunden")            # idle but connected
        else:
            ttk.Style(self.root).configure("Pill.TLabel", background=GOLD,
                                           foreground=WIN_BG)
            self.pill.configure(text=phase, background=GOLD, foreground=WIN_BG)

    def _on_champ_data(self, champs):
        self.champs = champs
        self.by_id = {c["id"]: c for c in champs}
        self.name_to_id = {}
        for c in champs:
            self.name_to_id[_normalize(c["name"])] = c["id"]
            self.name_to_id[_normalize(c["alias"])] = c["id"]
        self.champ_loaded = True
        self.pick_ids = self._resolve(self.pending.get("picks", []), MAX_PICKS)
        self.ban_ids = self._resolve(self.pending.get("bans", []), MAX_BANS)
        self._render_results()
        self._render_lists()

    def _resolve(self, names, limit):
        ids = []
        for name in names:
            cid = self.name_to_id.get(_normalize(name))
            if cid and cid not in ids:
                ids.append(cid)
            if len(ids) >= limit:
                break
        return ids

    def _on_icon(self, payload):
        cid, data = payload
        try:
            photo = self._thumb(data)
        except Exception:
            return
        self.icon_cache[cid] = photo
        live = []
        for lbl in self.icon_widgets.get(cid, []):
            try:
                if lbl is not None and lbl.winfo_exists():
                    lbl.configure(image=photo)
                    lbl.image = photo
                    live.append(lbl)
            except tk.TclError:
                pass
        self.icon_widgets[cid] = live

    def _notify(self):
        self._set_status("🎮 Spiel startet – zurück an den PC!")
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(4000, lambda: self.root.attributes("-topmost", False))
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            self.root.bell()

    # --------------------------------------------------------- config I/O -- #
    def _load_config(self):
        try:
            data = json.loads(CONFIG_PATH.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_config(self):
        if self.champ_loaded:
            picks = [self.by_id[i]["alias"] for i in self.pick_ids if i in self.by_id]
            bans = [self.by_id[i]["alias"] for i in self.ban_ids if i in self.by_id]
        else:
            picks = self.pending.get("picks", [])
            bans = self.pending.get("bans", [])
        data = {"picks": picks, "bans": bans,
                "auto_accept": self.auto_accept_on, "auto_ban": self.auto_ban_on}
        self.pending = data
        try:
            CONFIG_PATH.write_text(json.dumps(data, indent=2))
        except OSError:
            pass

    def _on_close(self):
        self._save_config()
        self.closing.set()
        self.root.destroy()

    # -------------------------------------------------------- scroll wheel -- #
    def _bind_wheel(self, canvas):
        def on_wheel(event):
            canvas.yview_scroll(int(-event.delta / 120), "units")
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", on_wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

    # -------------------------------------------------------- service loop -- #
    def _service(self):
        lcu = None
        last_phase = None
        state = {"hover": None, "warn_pick": False, "warn_ban": False}
        waiting = False
        while not self.closing.is_set():
            if lcu is None:
                lcu = LCU.connect()
                if lcu is None:
                    if not waiting:
                        self._post("status", ("warten", "Kein League-Client gefunden …"))
                        waiting = True
                    self.closing.wait(2)
                    continue
                try:
                    champs = lcu.champion_list()
                except (requests.RequestException, ValueError, KeyError):
                    lcu = None
                    self.closing.wait(2)
                    continue
                self.creds = (lcu.port, lcu.token)
                self._post("creds", (lcu.port, lcu.token))
                self._post("champ_data", champs)
                self._post("status", ("verbunden", "Verbunden mit dem League-Client."))
                waiting, last_phase = False, None

            try:
                phase = lcu.gameflow_phase()
            except requests.RequestException:
                self._post("status", ("warten", "Verbindung verloren – neu verbinden …"))
                lcu, self.creds, last_phase = None, None, None
                self.closing.wait(2)
                continue

            if phase != last_phase:
                self._post("phase", phase)
                if phase != "ChampSelect":
                    state = {"hover": None, "warn_pick": False, "warn_ban": False}

            if self.armed.is_set():
                try:
                    if phase == "ReadyCheck" and self.auto_accept_on:
                        rc = lcu.ready_check()
                        if rc and rc.get("playerResponse") == "None":
                            lcu.accept_ready_check()
                            self._post("log", "Queue angenommen ✔")
                    elif phase == "ChampSelect":
                        self._champ_select(lcu, state)
                    elif phase in ("GameStart", "InProgress") and \
                            last_phase not in ("GameStart", "InProgress"):
                        self._post("log", "Spiel startet!")
                        self._post("notify")
                except requests.RequestException:
                    lcu, self.creds, last_phase = None, None, None
                    continue

            last_phase = phase
            self.closing.wait(POLL_SECONDS)

    def _champ_select(self, lcu, state):
        session = lcu.champ_select_session()
        if not session:
            return
        my_cell = session.get("localPlayerCellId")
        my_team = session.get("myTeam") or []
        ally_intents = set()
        for m in my_team:
            if m.get("cellId") != my_cell:
                ally_intents.add(m.get("championPickIntent"))
                ally_intents.add(m.get("championId"))
        ally_intents.discard(0)
        ally_intents.discard(None)

        actions = [a for group in (session.get("actions") or []) for a in group]
        mine = [a for a in actions if a.get("actorCellId") == my_cell]
        pick = next((a for a in mine if a.get("type") == "pick"
                     and not a.get("completed")), None)
        ban = next((a for a in mine if a.get("type") == "ban"
                    and not a.get("completed") and a.get("isInProgress")), None)

        pick_ids = list(self.pick_ids)
        ban_ids = list(self.ban_ids)

        banned = self._banned_set(session, actions)

        # --- Auto-ban (only on our turn) ---------------------------------- #
        if self.auto_ban_on and ban and ban_ids:
            target = next((c for c in ban_ids if c not in banned
                           and c not in pick_ids and c not in ally_intents), None)
            if target:
                if lcu.complete_action(ban["id"], target).ok:
                    self._post("log", f"{self._name(target)} gebannt ✔")
            elif not state["warn_ban"]:
                self._post("log", "Kein Bann-Champion verfügbar – übersprungen.")
                state["warn_ban"] = True

        # --- Pick: pre-hover, then lock on our turn ----------------------- #
        if pick and pick_ids:
            pickable = lcu.pickable_champion_ids()
            # Champions another player already locked in are off the table.
            taken = {a["championId"] for a in actions
                     if a.get("type") == "pick" and a.get("completed")
                     and a.get("actorCellId") != my_cell and a.get("championId")}
            # Exclude the ban set ourselves so a banned #1 always falls through
            # to #2 — even if pickable-champion-ids still lists the banned champ
            # (it doesn't reliably drop bans, which would otherwise wedge us
            # retrying an un-lockable pick).
            target = next((c for c in pick_ids if c not in banned
                           and c not in taken
                           and (not pickable or c in pickable)), None)
            if target is None:
                if not state["warn_pick"]:
                    self._post("log", "Kein Pick-Champion verfügbar – bitte manuell.")
                    state["warn_pick"] = True
            elif pick.get("isInProgress"):
                if lcu.complete_action(pick["id"], target).ok:
                    self._post("log", f"{self._name(target)} gelockt ✔")
            elif state["hover"] != target:
                if lcu.hover_champion(pick["id"], target).ok:
                    self._post("log", f"{self._name(target)} vorgemerkt")
                    state["hover"] = target

    @staticmethod
    def _banned_set(session, actions):
        """Champion ids banned so far: completed ban actions + team ban lists."""
        banned = {a["championId"] for a in actions
                  if a.get("type") == "ban" and a.get("completed")
                  and a.get("championId")}
        info = session.get("bans") or {}
        banned |= set(info.get("myTeamBans") or [])
        banned |= set(info.get("theirTeamBans") or [])
        banned.discard(0)
        return banned

    def _icon_worker(self):
        icl = None
        icl_creds = None
        while not self.closing.is_set():
            try:
                cid = self.icon_queue.get(timeout=0.4)
            except queue.Empty:
                continue
            creds = self.creds
            if not creds:
                continue
            if icl is None or icl_creds != creds:
                icl, icl_creds = LCU(*creds), creds
            try:
                data = icl.champion_icon(cid)
                if data:
                    self._post("icon", (cid, data))
            except requests.RequestException:
                pass


def main():
    root = tk.Tk()
    AutoPickApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
