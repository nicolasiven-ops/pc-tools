"""PC Tools — a small collection of handy Windows PC controls.

Two tools for now:
  * Shutdown timer  — shut the PC down after a chosen delay, with preset
                      chips, fine adjust and a live "off at HH:MM" preview.
  * Screen dimmer   — black out every monitor until the next click or key.

The standalone .exe is built by GitHub Actions (.github/workflows/build.yml);
see README.md for how to download and run it.
"""

import sys
import subprocess
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox

IS_WINDOWS = sys.platform == "win32"

MIN_MINUTES = 15
MAX_MINUTES = 12 * 60
DEFAULT_MINUTES = 120
PRESETS = [(30, "30 min"), (60, "1 h"), (120, "2 h"), (180, "3 h")]


def format_clock(seconds):
    """Format a second count as M:SS, or H:MM:SS once it passes an hour."""
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def humanize_minutes(minutes):
    """Turn a minute count into a friendly label, e.g. 135 -> '2 h 15 min'."""
    hours, mins = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} h")
    if mins:
        parts.append(f"{mins} min")
    return " ".join(parts) if parts else "0 min"


def virtual_screen_geometry(root):
    """Return (width, height, x, y) of the box spanning every monitor.

    On Windows the OS reports the virtual-screen bounding box so a single
    overlay can cover all monitors; elsewhere we fall back to the primary one.
    """
    if IS_WINDOWS:
        import ctypes

        user32 = ctypes.windll.user32
        SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
        SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
        return (
            user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        )
    return root.winfo_screenwidth(), root.winfo_screenheight(), 0, 0


def dim_screen(root):
    """Cover every monitor with a black overlay until a click or key press."""
    width, height, x, y = virtual_screen_geometry(root)

    overlay = tk.Toplevel(root)
    overlay.overrideredirect(True)        # no title bar or borders
    overlay.geometry(f"{width}x{height}+{x}+{y}")
    overlay.configure(bg="black")
    overlay.attributes("-topmost", True)
    overlay.config(cursor="none")

    def close(_event=None):
        overlay.destroy()

    # Any mouse button or key brings the screen back; Esc is an explicit failsafe.
    overlay.bind("<Button>", close)
    overlay.bind("<Key>", close)
    overlay.bind("<Escape>", close)

    overlay.focus_force()
    try:
        overlay.grab_set()                # route stray input to the overlay
    except tk.TclError:
        pass


class PCToolsApp:
    def __init__(self, root):
        self.root = root
        self.timer_job = None
        self.running = False
        self.remaining = 0
        self.end_time = None
        self.duration_var = tk.IntVar(value=DEFAULT_MINUTES)
        self.controls = []
        self._build_ui()
        self._preview_loop()              # keep the idle "off at HH:MM" live

    def _build_ui(self):
        self.root.title("PC Tools")
        self.root.resizable(False, False)

        outer = ttk.Frame(self.root, padding=16)
        outer.grid(sticky="nsew")

        # --- Shutdown timer ------------------------------------------------ #
        box = ttk.LabelFrame(outer, text="Ausschalt-Timer", padding=12)
        box.grid(row=0, column=0, sticky="ew")

        # Preset chips — Toolbutton-styled radios highlight the active one.
        chips = ttk.Frame(box)
        chips.grid(row=0, column=0, sticky="w")
        for i, (mins, label) in enumerate(PRESETS):
            chip = ttk.Radiobutton(
                chips, text=label, value=mins, variable=self.duration_var,
                style="Toolbutton", width=6, command=self._update_preview,
            )
            chip.grid(row=0, column=i, padx=(0, 4))
            self.controls.append(chip)

        # Fine adjust.
        steppers = ttk.Frame(box)
        steppers.grid(row=1, column=0, sticky="w", pady=(8, 0))
        minus = ttk.Button(steppers, text="− 15 min", width=9,
                           command=lambda: self._adjust(-15))
        minus.grid(row=0, column=0, padx=(0, 4))
        plus = ttk.Button(steppers, text="+ 15 min", width=9,
                          command=lambda: self._adjust(15))
        plus.grid(row=0, column=1)
        self.controls += [minus, plus]

        # Big status line: end time while idle, countdown while running.
        self.headline_var = tk.StringVar()
        ttk.Label(box, textvariable=self.headline_var, font=("Segoe UI", 16)).grid(
            row=2, column=0, sticky="w", pady=(12, 0)
        )
        self.sub_var = tk.StringVar()
        ttk.Label(box, textvariable=self.sub_var, foreground="#666").grid(
            row=3, column=0, sticky="w"
        )

        # Start / cancel.
        buttons = ttk.Frame(box)
        buttons.grid(row=4, column=0, sticky="w", pady=(12, 0))
        self.start_btn = ttk.Button(buttons, text="Start", command=self.start_timer)
        self.start_btn.grid(row=0, column=0, padx=(0, 6))
        self.cancel_btn = ttk.Button(
            buttons, text="Abbrechen", command=self.cancel_timer, state="disabled"
        )
        self.cancel_btn.grid(row=0, column=1)

        # --- Screen dimmer ------------------------------------------------- #
        dim_box = ttk.LabelFrame(outer, text="Bildschirm abdunkeln", padding=12)
        dim_box.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        ttk.Label(
            dim_box,
            text="Macht alle Monitore schwarz, bis du klickst oder eine Taste drückst.",
            wraplength=300, justify="left",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(dim_box, text="Jetzt abdunkeln", command=self._dim).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )

    # --- duration selection ------------------------------------------------ #
    def _adjust(self, delta):
        new = max(MIN_MINUTES, min(MAX_MINUTES, self.duration_var.get() + delta))
        self.duration_var.set(new)
        self._update_preview()

    def _update_preview(self):
        """Paint the idle preview: when does the PC switch off, and in how long."""
        minutes = self.duration_var.get()
        end = datetime.now() + timedelta(minutes=minutes)
        self.headline_var.set(f"Aus um {end:%H:%M} Uhr")
        self.sub_var.set(f"in {humanize_minutes(minutes)}")

    def _preview_loop(self):
        if not self.running:
            self._update_preview()        # roll the end time with the wall clock
        self.root.after(1000, self._preview_loop)

    # --- shutdown timer ---------------------------------------------------- #
    def start_timer(self):
        minutes = self.duration_var.get()
        self.remaining = minutes * 60
        self.end_time = datetime.now() + timedelta(seconds=self.remaining)
        self.running = True
        self._set_running(True)
        self._tick()

    def _tick(self):
        self.headline_var.set(format_clock(max(self.remaining, 0)))
        self.sub_var.set(f"Herunterfahren um {self.end_time:%H:%M} Uhr")
        if self.remaining <= 0:
            self._do_shutdown()
            return
        self.remaining -= 1
        self.timer_job = self.root.after(1000, self._tick)

    def cancel_timer(self):
        if self.timer_job is not None:
            self.root.after_cancel(self.timer_job)
            self.timer_job = None
        self.running = False
        self._set_running(False)
        self._update_preview()            # back to the live end-time preview

    def _do_shutdown(self):
        self.timer_job = None
        self.running = False
        self._set_running(False)
        self.headline_var.set("PC wird heruntergefahren …")
        self.sub_var.set("")
        if IS_WINDOWS:
            # Graceful shutdown — Windows still prompts on unsaved work.
            subprocess.run(["shutdown", "/s", "/t", "0"])
        else:
            messagebox.showinfo(
                "PC Tools", "Das Herunterfahren funktioniert nur unter Windows."
            )

    def _set_running(self, running):
        state = "disabled" if running else "normal"
        for widget in self.controls:
            widget.config(state=state)
        self.start_btn.config(state="disabled" if running else "normal")
        self.cancel_btn.config(state="normal" if running else "disabled")

    # --- screen dimmer ----------------------------------------------------- #
    def _dim(self):
        dim_screen(self.root)


def main():
    root = tk.Tk()
    PCToolsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
