"""LoL Auto-Pick — accepts your queue, picks a champion and pings you in-game.

A small companion that talks to the local League client (see lcu.py) and, while
running, does three things automatically:

  1. Accepts the ready-check as soon as a match is found.
  2. In champion select, picks the highest-priority champion from your list of
     five that is still available — so if your first choice gets banned or
     taken, it falls through to the next.
  3. Raises the window and plays a sound the moment the game launches, so you
     can step away from the keyboard during the queue.

The League client REST API is the same one Riot's own client uses. This only
automates client convenience (no in-game scripting), but note that any client
automation is technically against Riot's Terms of Service — use at your own
risk. See README.md.
"""

import json
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import scrolledtext, ttk

import requests

from lcu import LCU, _normalize

NUM_SLOTS = 5
POLL_SECONDS = 1.0
CONFIG_PATH = Path.home() / ".lol_autopick.json"


class AutoPickApp:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()               # worker -> GUI messages
        self.stop_event = threading.Event()
        self.worker = None

        self.slot_vars = [tk.StringVar() for _ in range(NUM_SLOTS)]
        self.auto_accept_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Bereit.")

        self._build_ui()
        self._load_config()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._drain_events()

    # ------------------------------------------------------------------ UI -- #
    def _build_ui(self):
        self.root.title("LoL Auto-Pick")
        self.root.resizable(False, False)

        outer = ttk.Frame(self.root, padding=16)
        outer.grid(sticky="nsew")

        # --- Champion priority -------------------------------------------- #
        champ_box = ttk.LabelFrame(outer, text="Champion-Priorität", padding=12)
        champ_box.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            champ_box,
            text="Von oben nach unten. Gebannte oder schon gepickte Champions "
                 "werden übersprungen.",
            wraplength=320, justify="left", foreground="#666",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self.slot_boxes = []
        for i, var in enumerate(self.slot_vars):
            ttk.Label(champ_box, text=f"{i + 1}.").grid(
                row=i + 1, column=0, sticky="w", padx=(0, 6), pady=2
            )
            combo = ttk.Combobox(champ_box, textvariable=var, width=24)
            combo.grid(row=i + 1, column=1, sticky="ew", pady=2)
            self.slot_boxes.append(combo)

        # --- Options ------------------------------------------------------ #
        opts = ttk.Frame(outer)
        opts.grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Checkbutton(
            opts, text="Queue automatisch annehmen", variable=self.auto_accept_var
        ).grid(row=0, column=0, sticky="w")

        # --- Start / stop ------------------------------------------------- #
        controls = ttk.Frame(outer)
        controls.grid(row=2, column=0, sticky="w", pady=(12, 0))
        self.start_btn = ttk.Button(controls, text="Start", command=self.start)
        self.start_btn.grid(row=0, column=0, padx=(0, 6))
        self.stop_btn = ttk.Button(
            controls, text="Stopp", command=self.stop, state="disabled"
        )
        self.stop_btn.grid(row=0, column=1)

        ttk.Label(
            outer, textvariable=self.status_var, font=("Segoe UI", 12)
        ).grid(row=3, column=0, sticky="w", pady=(12, 0))

        # --- Activity log ------------------------------------------------- #
        self.log = scrolledtext.ScrolledText(
            outer, width=46, height=12, state="disabled",
            font=("Consolas", 9), wrap="word",
        )
        self.log.grid(row=4, column=0, sticky="ew", pady=(8, 0))

    # ----------------------------------------------------------- config I/O -- #
    def _load_config(self):
        try:
            data = json.loads(CONFIG_PATH.read_text())
        except (OSError, ValueError):
            return
        for var, name in zip(self.slot_vars, data.get("champions", [])):
            var.set(name)
        self.auto_accept_var.set(bool(data.get("auto_accept", True)))

    def _save_config(self):
        data = {
            "champions": [var.get() for var in self.slot_vars],
            "auto_accept": self.auto_accept_var.get(),
        }
        try:
            CONFIG_PATH.write_text(json.dumps(data, indent=2))
        except OSError:
            pass

    # -------------------------------------------------------- start / stop -- #
    def start(self):
        self._save_config()
        config = {
            "champions": [var.get().strip() for var in self.slot_vars],
            "auto_accept": self.auto_accept_var.get(),
        }
        if not any(config["champions"]):
            self.status_var.set("Bitte mindestens einen Champion eintragen.")
            return

        self.stop_event.clear()
        self.worker = threading.Thread(
            target=self._run_worker, args=(config,), daemon=True
        )
        self.worker.start()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("Läuft – warte auf League-Client …")

    def stop(self):
        self.stop_event.set()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("Gestoppt.")

    def _on_close(self):
        self._save_config()
        self.stop_event.set()
        self.root.destroy()

    # ----------------------------------------------- worker -> GUI plumbing -- #
    def _post(self, kind, payload=None):
        """Called from the worker thread; never touches tk widgets directly."""
        self.events.put((kind, payload))

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "status":
                    self.status_var.set(payload)
                elif kind == "champions":
                    for combo in self.slot_boxes:
                        combo["values"] = payload
                elif kind == "notify":
                    self._notify_game_start()
        except queue.Empty:
            pass
        self.root.after(150, self._drain_events)

    def _append_log(self, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.config(state="normal")
        self.log.insert("end", f"[{stamp}] {message}\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _notify_game_start(self):
        self.status_var.set("🎮 Spiel startet – zurück an den PC!")
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(4000, lambda: self.root.attributes("-topmost", False))
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            self.root.bell()

    # --------------------------------------------------------------- worker -- #
    def _run_worker(self, config):
        """Background loop: poll the client and drive the automation."""
        lcu = None
        id_to_name = {}
        priority_ids = []
        last_phase = None
        hovered = None
        warned_unavailable = False
        waiting_logged = False

        while not self.stop_event.is_set():
            # (Re)connect to the client if we have no live session.
            if lcu is None:
                lcu = LCU.connect()
                if lcu is None:
                    if not waiting_logged:
                        self._post("log", "Kein League-Client gefunden – warte …")
                        waiting_logged = True
                    time.sleep(2)
                    continue
                try:
                    name_to_id, id_to_name, names = lcu.load_champions()
                except (requests.RequestException, ValueError):
                    lcu = None
                    time.sleep(2)
                    continue
                self._post("champions", names)
                priority_ids = _resolve(config["champions"], name_to_id, self._post)
                if not priority_ids:
                    self._post("log", "Keiner der Namen ließ sich zuordnen – stoppe.")
                    self._post("status", "Champion-Namen prüfen.")
                    return
                self._post("status", "Verbunden mit dem League-Client.")
                self._post("log", "Verbunden ✔")
                waiting_logged = False

            try:
                phase = lcu.gameflow_phase()
            except requests.RequestException:
                self._post("log", "Verbindung verloren – verbinde neu …")
                lcu, last_phase, hovered = None, None, None
                time.sleep(2)
                continue

            if phase != last_phase:
                self._post("log", f"Status: {phase}")
                if phase != "ChampSelect":
                    hovered, warned_unavailable = None, False

            try:
                if phase == "ReadyCheck" and config["auto_accept"]:
                    rc = lcu.ready_check()
                    if rc and rc.get("playerResponse") == "None":
                        lcu.accept_ready_check()
                        self._post("log", "Queue angenommen ✔")
                elif phase == "ChampSelect":
                    hovered, warned_unavailable = self._champ_select(
                        lcu, priority_ids, id_to_name, hovered, warned_unavailable
                    )
                elif phase in ("GameStart", "InProgress") and last_phase not in (
                    "GameStart", "InProgress",
                ):
                    self._post("log", "Spiel startet!")
                    self._post("notify")
            except requests.RequestException:
                lcu, last_phase, hovered = None, None, None
                continue

            last_phase = phase
            time.sleep(POLL_SECONDS)

    def _champ_select(self, lcu, priority_ids, id_to_name, hovered, warned):
        """Hover/lock the best available champion. Returns (hovered, warned)."""
        session = lcu.champ_select_session()
        if not session:
            return hovered, warned

        my_cell = session.get("localPlayerCellId")
        my_pick = None
        for group in session.get("actions") or []:
            for action in group:
                if action.get("actorCellId") == my_cell and action.get("type") == "pick":
                    my_pick = action
        if not my_pick or my_pick.get("completed"):
            return hovered, warned                 # nothing to do / already locked

        pickable = lcu.pickable_champion_ids()
        target = next((cid for cid in priority_ids if cid in pickable), None)
        if target is None:
            if not warned:
                self._post("log", "Kein Prioritäts-Champion verfügbar – bitte manuell.")
                warned = True
            return hovered, warned

        action_id = my_pick["id"]
        if my_pick.get("isInProgress"):            # our turn -> lock it in
            if lcu.lock_champion(action_id, target).ok:
                self._post("log", f"{id_to_name.get(target, target)} gelockt ✔")
        elif hovered != target:                    # pre-hover to signal intent
            if lcu.hover_champion(action_id, target).ok:
                self._post("log", f"{id_to_name.get(target, target)} vorgemerkt")
                hovered = target
        return hovered, warned


def _resolve(names, name_to_id, post):
    """Map typed champion names to ids, in order, logging any that don't match."""
    ids = []
    for name in names:
        if not name:
            continue
        cid = name_to_id.get(_normalize(name))
        if cid is None:
            post("log", f"Unbekannter Champion: {name!r}")
        elif cid not in ids:
            ids.append(cid)
    return ids


def main():
    root = tk.Tk()
    AutoPickApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
