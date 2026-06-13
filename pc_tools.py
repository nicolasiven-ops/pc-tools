"""PC Tools — a small collection of handy Windows PC controls.

Two tools for now:
  * Shutdown timer  — shut the PC down after a configurable delay.
  * Screen dimmer   — black out every monitor until the next click or key.

The standalone .exe is built by GitHub Actions (.github/workflows/build.yml);
see README.md for how to download and run it.
"""

import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

IS_WINDOWS = sys.platform == "win32"


def format_duration(seconds):
    """Format a second count as M:SS, or H:MM:SS once it passes an hour."""
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


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
        self.remaining = 0
        self._build_ui()

    def _build_ui(self):
        self.root.title("PC Tools")
        self.root.resizable(False, False)

        outer = ttk.Frame(self.root, padding=16)
        outer.grid(sticky="nsew")

        # --- Shutdown timer ------------------------------------------------ #
        timer_box = ttk.LabelFrame(outer, text="Ausschalt-Timer", padding=12)
        timer_box.grid(row=0, column=0, sticky="ew")

        entry_row = ttk.Frame(timer_box)
        entry_row.grid(row=0, column=0, sticky="w")
        ttk.Label(entry_row, text="Minuten:").grid(row=0, column=0, padx=(0, 6))
        self.minutes_var = tk.StringVar(value="30")
        self.minutes_entry = ttk.Entry(entry_row, textvariable=self.minutes_var, width=8)
        self.minutes_entry.grid(row=0, column=1)

        presets_row = ttk.Frame(timer_box)
        presets_row.grid(row=1, column=0, sticky="w", pady=(8, 0))
        for i, mins in enumerate((15, 30, 60, 90)):
            ttk.Button(
                presets_row, text=f"{mins} min", width=7,
                command=lambda m=mins: self.minutes_var.set(str(m)),
            ).grid(row=0, column=i, padx=(0, 4))

        self.countdown_var = tk.StringVar(value="Kein Timer aktiv.")
        ttk.Label(timer_box, textvariable=self.countdown_var, font=("Segoe UI", 14)).grid(
            row=2, column=0, sticky="w", pady=(12, 0)
        )

        buttons_row = ttk.Frame(timer_box)
        buttons_row.grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.start_btn = ttk.Button(buttons_row, text="Start", command=self.start_timer)
        self.start_btn.grid(row=0, column=0, padx=(0, 6))
        self.cancel_btn = ttk.Button(
            buttons_row, text="Abbrechen", command=self.cancel_timer, state="disabled"
        )
        self.cancel_btn.grid(row=0, column=1)

        # --- Screen dimmer ------------------------------------------------- #
        dim_box = ttk.LabelFrame(outer, text="Bildschirm abdunkeln", padding=12)
        dim_box.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        ttk.Label(
            dim_box,
            text="Macht alle Monitore schwarz, bis du klickst oder eine Taste drückst.",
            wraplength=280, justify="left",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(dim_box, text="Jetzt abdunkeln", command=self._dim).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )

    # --- shutdown timer ---------------------------------------------------- #
    def start_timer(self):
        raw = self.minutes_var.get().strip().replace(",", ".")
        try:
            minutes = float(raw)
        except ValueError:
            messagebox.showerror("PC Tools", "Bitte eine gültige Zahl an Minuten eingeben.")
            return
        if minutes <= 0:
            messagebox.showerror("PC Tools", "Die Zeit muss größer als 0 sein.")
            return
        self.remaining = int(round(minutes * 60))
        self._set_running(True)
        self._tick()

    def _tick(self):
        if self.remaining <= 0:
            self._do_shutdown()
            return
        self.countdown_var.set(f"Herunterfahren in {format_duration(self.remaining)}")
        self.remaining -= 1
        self.timer_job = self.root.after(1000, self._tick)

    def cancel_timer(self):
        if self.timer_job is not None:
            self.root.after_cancel(self.timer_job)
            self.timer_job = None
        self._set_running(False)
        self.countdown_var.set("Timer abgebrochen.")

    def _do_shutdown(self):
        self.timer_job = None
        self._set_running(False)
        self.countdown_var.set("PC wird heruntergefahren …")
        if IS_WINDOWS:
            # Graceful shutdown — Windows still prompts on unsaved work.
            subprocess.run(["shutdown", "/s", "/t", "0"])
        else:
            messagebox.showinfo(
                "PC Tools", "Das Herunterfahren funktioniert nur unter Windows."
            )

    def _set_running(self, running):
        self.start_btn.config(state="disabled" if running else "normal")
        self.cancel_btn.config(state="normal" if running else "disabled")
        self.minutes_entry.config(state="disabled" if running else "normal")

    # --- screen dimmer ----------------------------------------------------- #
    def _dim(self):
        dim_screen(self.root)


def main():
    root = tk.Tk()
    PCToolsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
