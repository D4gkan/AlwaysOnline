from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import tkinter as tk
import time
from pathlib import Path
from tkinter import messagebox, ttk

from typing import List

from app.accounts import store as account_store
from app.accounts.models import Account, AccountValidationError, Site
from app import __version__
from app.notify.discord import DiscordNotifier

ACTIVE_ACCOUNT_PROCESSES: dict[str, subprocess.Popen] = {}
LAUNCH_INTERVAL_MS = 70_000


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _launch_env_for_size(large: bool) -> dict[str, str]:
    env = os.environ.copy()
    env["BROWSER"] = "brave"
    if os.name == "nt":
        brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
        if os.path.exists(brave_path):
            env["BRAVE_PATH"] = brave_path
    if large:
        env["WINDOW_WIDTH"] = "640"
        env["WINDOW_HEIGHT"] = "640"
        env["BROWSER_ZOOM_PERCENT"] = "80"
    else:
        env["WINDOW_WIDTH"] = "256"
        env["WINDOW_HEIGHT"] = "256"
        env["BROWSER_ZOOM_PERCENT"] = "60"
    return env


def create_account_record(name: str, csfloat_url: str, csgoempire_url: str) -> Account:
    """Persist an account record locally without storing secrets or cookies in app code."""
    return account_store.create(name, csfloat_url, csgoempire_url)


def launch_account_record(account: Account, *, large: bool = False, launch_sequence_index: int | None = None):
    """Launch a saved account in a visible console window so the browser session stays open on Windows."""
    cmd = [sys.executable, "-m", "app.cli.main", "account", "launch", account.name]
    env = _launch_env_for_size(large)
    if launch_sequence_index is not None:
        env["LAUNCH_SEQUENCE_INDEX"] = str(launch_sequence_index)
    if os.name == "nt":
        # The GUI app lives in a hidden pythonw process. Launch the account CLI in a
        # real console window so it stays alive and the browser windows remain visible.
        creation_flags = subprocess.CREATE_NEW_CONSOLE
        proc = subprocess.Popen(
            cmd,
            cwd=str(_project_root()),
            creationflags=creation_flags,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
    else:
        proc = subprocess.Popen(
            cmd,
            cwd=str(_project_root()),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
    ACTIVE_ACCOUNT_PROCESSES[account.name] = proc
    return proc


def close_browser_processes(proc=None, account_name: str | None = None) -> None:
    """Close the launched subprocess and any child browser processes created for the account."""
    if proc is None and account_name is None:
        return

    if proc is None and account_name in ACTIVE_ACCOUNT_PROCESSES:
        proc = ACTIVE_ACCOUNT_PROCESSES[account_name]

    if proc is not None:
        target_name = account_name
        if target_name is None:
            for name, running in list(ACTIVE_ACCOUNT_PROCESSES.items()):
                if running is proc or getattr(running, "pid", None) == getattr(proc, "pid", None):
                    target_name = name
                    break
        if target_name and target_name in ACTIVE_ACCOUNT_PROCESSES:
            del ACTIVE_ACCOUNT_PROCESSES[target_name]

    if proc is None:
        return

    try:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


def save_current_session_and_keep(account: Account):
    """Save account metadata and ensure its profile directories exist for persisted browser state."""
    account_store.save(account)
    for site in (Site.CSFLOAT, Site.CSGOEMPIRE):
        account.profile_dir(site).mkdir(parents=True, exist_ok=True)
    return account


def confirm_done_and_save(account: Account, is_done: bool, proc=None) -> bool:
    """Only save the account after the user confirms they are done logging in."""
    if not is_done:
        return False
    close_browser_processes(proc)
    account_store.save(account)
    return True


def launch_account_by_name(name: str, *, large: bool = False, launch_sequence_index: int | None = None):
    account = account_store.load(name)
    return launch_account_record(account, large=large, launch_sequence_index=launch_sequence_index)


def launch_all_accounts_sequential(
    root: tk.Tk,
    names: list[str],
    launched: list[str],
    index: int = 0,
    on_launch=None,
    on_error=None,
) -> None:
    """Launch accounts sequentially with 70-second intervals."""
    if index >= len(names):
        # All launches complete
        return
    
    name = names[index]
    try:
        # Pass the current sequence index so windows position based on launch order
        launch_account_by_name(name, large=False, launch_sequence_index=index)
        launched.append(name)
        if on_launch:
            on_launch(name, index)
    except Exception as exc:
        if on_error:
            on_error(name, exc, index)
    
    # Keep each launch in the same callback chain so every account gets its own delay.
    if index + 1 < len(names):
        root.after(
            LAUNCH_INTERVAL_MS,
            lambda: launch_all_accounts_sequential(
                root, names, launched, index + 1, on_launch, on_error
            ),
        )


def launch_all_accounts() -> list[str]:
    names = account_store.list_names()
    launched: list[str] = []
    for name in names:
        try:
            launch_account_by_name(name, large=False)
            launched.append(name)
        except Exception:
            continue
    return launched


def kill_all_accounts() -> list[str]:
    killed: list[str] = []
    for name, proc in list(ACTIVE_ACCOUNT_PROCESSES.items()):
        try:
            close_browser_processes(proc, name)
            killed.append(name)
        except Exception:
            continue
    return killed


def test_active_account_activity() -> list[str]:
    """Ask each launched account process to scroll its open browser sessions."""
    tested: list[str] = []
    for name, proc in list(ACTIVE_ACCOUNT_PROCESSES.items()):
        try:
            if proc.poll() is not None or proc.stdin is None:
                continue
            proc.stdin.write("test\n")
            proc.stdin.flush()
            tested.append(name)
        except (BrokenPipeError, OSError, ValueError):
            continue
    return tested


def create_account_and_launch(name: str, csfloat_url: str, csgoempire_url: str):
    account = create_account_record(name, csfloat_url, csgoempire_url)
    launch_account_record(account)
    return account


# --------------------------------------------------------------------------
# Design tokens
# --------------------------------------------------------------------------

class Palette:
    BG = "#0a0a0c"          # app background
    PANEL = "#0a0a0c"       # header background (same as app, seamless)
    CARD = "#131316"        # card surfaces
    CARD_BORDER = "#232327"
    FIELD = "#18181c"       # input backgrounds
    FIELD_BORDER = "#28282e"
    FIELD_BORDER_FOCUS = "#3a3a42"
    DIVIDER = "#1c1c20"

    TEXT = "#eeeef0"
    TEXT_MUTED = "#8b8b92"
    TEXT_FAINT = "#5c5c63"

    ACCENT = "#5b8cff"
    ACCENT_HOVER = "#6f99ff"
    ACCENT_TEXT = "#0a0a0c"

    SURFACE = "#1c1c21"
    SURFACE_HOVER = "#242429"

    DANGER = "#e5484d"
    DANGER_HOVER = "#ef5a5f"
    DANGER_TEXT = "#0a0a0c"

    FONT_FAMILY = "Segoe UI" if os.name == "nt" else "Helvetica"


def _font(size, weight="normal"):
    return (Palette.FONT_FAMILY, size, weight)


def _rounded_points(x1, y1, x2, y2, r):
    return [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]


# --------------------------------------------------------------------------
# Rounded card: a Canvas draws the rounded surface, a Frame inset inside it
# holds the real widgets. Frame is inset by >= radius so its square corners
# never overlap the canvas's rounded corners.
# --------------------------------------------------------------------------

class RoundedCard(tk.Frame):
    def __init__(self, parent, bg=Palette.CARD, border=Palette.CARD_BORDER, radius=16):
        super().__init__(parent, bg=parent["bg"])
        self.canvas = tk.Canvas(self, bg=parent["bg"], highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.card_bg = bg
        self.border_color = border
        self.radius = radius
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.content = tk.Frame(self.inner, bg=bg, padx=18, pady=14)
        self.content.pack(fill="both", expand=True)
        self._win = None
        self.canvas.bind("<Configure>", self._redraw)

    def _redraw(self, event=None):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w < 4 or h < 4:
            return
        self.canvas.delete("bg")
        self.canvas.create_polygon(
            _rounded_points(1, 1, w - 1, h - 1, self.radius),
            smooth=True, fill=self.card_bg, outline=self.border_color, width=1, tags="bg",
        )
        self.canvas.tag_lower("bg")
        iw, ih = max(w - 2 * self.radius, 1), max(h - 2 * self.radius, 1)
        if self._win is None:
            self._win = self.canvas.create_window(self.radius, self.radius, anchor="nw", window=self.inner, width=iw, height=ih)
        else:
            self.canvas.coords(self._win, self.radius, self.radius)
            self.canvas.itemconfig(self._win, width=iw, height=ih)


# --------------------------------------------------------------------------
# Rounded entry: canvas draws a rounded, bordered field; a borderless tk.Entry
# sits inside it. Border color shifts to the accent on focus.
# --------------------------------------------------------------------------

class RoundedEntry(tk.Frame):
    def __init__(self, parent, textvariable=None, radius=9, height=40, **kwargs):
        super().__init__(parent, bg=parent["bg"])
        self.radius = radius
        self.border_color = Palette.FIELD_BORDER
        self.fill_color = Palette.FIELD
        self.canvas = tk.Canvas(self, height=height, bg=parent["bg"], highlightthickness=0, bd=0)
        self.canvas.pack(fill="x")
        self.entry = tk.Entry(
            self.canvas,
            textvariable=textvariable,
            bg=Palette.FIELD,
            fg=Palette.TEXT,
            insertbackground=Palette.TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=_font(10),
            **kwargs,
        )
        self._bg_id = None
        self._win = None
        self.canvas.bind("<Configure>", self._redraw)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)

    def _redraw(self, event=None):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w < 4 or h < 4:
            return
        self.canvas.delete("bg")
        self.canvas.create_polygon(
            _rounded_points(1, 1, w - 1, h - 1, self.radius),
            smooth=True, fill=self.fill_color, outline=self.border_color, width=1, tags="bg",
        )
        self.canvas.tag_lower("bg")
        if self._win is None:
            self._win = self.canvas.create_window(14, h / 2, anchor="w", window=self.entry, width=max(w - 28, 1))
        else:
            self.canvas.coords(self._win, 14, h / 2)
            self.canvas.itemconfig(self._win, width=max(w - 28, 1))

    def _on_focus_in(self, event=None):
        self.border_color = Palette.ACCENT
        self._redraw()

    def _on_focus_out(self, event=None):
        self.border_color = Palette.FIELD_BORDER
        self._redraw()


# --------------------------------------------------------------------------
# Rounded, hoverable canvas button
# --------------------------------------------------------------------------

class RoundButton(tk.Canvas):
    """A flat, rounded-corner button drawn on a canvas (tk.Button has no radius)."""

    def __init__(
        self,
        parent,
        text,
        command=None,
        bg=Palette.SURFACE,
        hover=Palette.SURFACE_HOVER,
        fg=Palette.TEXT,
        height=40,
        radius=10,
        font=None,
    ):
        super().__init__(
            parent,
            height=height,
            bg=parent["bg"],
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.command = command
        self.text = text
        self.bg_color = bg
        self.hover_color = hover
        self.fg_color = fg
        self.radius = radius
        self.height = height
        self.font = font or _font(10, "bold")
        self._current = bg

        self.bind("<Configure>", self._redraw)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kwargs)

    def _redraw(self, event=None):
        self.delete("all")
        w = self.winfo_width() or 1
        h = self.winfo_height() or self.height
        self._rounded_rect(1, 1, w - 1, h - 1, self.radius, fill=self._current, outline="")
        self.create_text(w / 2, h / 2, text=self.text, fill=self.fg_color, font=self.font)

    def _on_enter(self, event=None):
        self._current = self.hover_color
        self._redraw()

    def _on_leave(self, event=None):
        self._current = self.bg_color
        self._redraw()

    def _on_click(self, event=None):
        self._current = self.bg_color
        self._redraw()

    def _on_release(self, event=None):
        self._current = self.hover_color
        self._redraw()
        if self.command:
            self.command()


class AccountManagerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Always Online")
        self.geometry("1000x540")
        self.minsize(920, 500)
        self.configure(bg=Palette.BG)

        self.name_var = tk.StringVar()
        self.csfloat_var = tk.StringVar(value="https://csfloat.com/stall/me")
        self.csgoempire_var = tk.StringVar(value="https://csgoempire.com/deposit")
        self.status_var = tk.StringVar(value="Ready")
        self.launch_timer_var = tk.StringVar(value="Next launch: --")
        self._launch_timer_after_id = None
        self._launch_sequence_running = False
        self._launch_deadline = None

        self._setup_theme()
        self._build_ui()
        self.refresh_account_list()

    # ------------------------------------------------------------------
    def _setup_theme(self):
        # Kill Tk's default 2px sunken/etched borders — this is what shows up
        # as light/white edges around entries, frames and buttons on a dark bg.
        self.option_add("*Font", f"{{{Palette.FONT_FAMILY}}} 10")
        self.option_add("*BorderWidth", 0)
        self.option_add("*HighlightThickness", 0)
        self.option_add("*Relief", "flat")
        self.option_add("*Background", Palette.BG)
        self.option_add("*Foreground", Palette.TEXT)
        self.option_add("*activeBackground", Palette.SURFACE_HOVER)
        self.option_add("*activeForeground", Palette.TEXT)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # clam's default TCombobox draws a light/dark bevel (lightcolor /
        # darkcolor) around the field even when borderwidth is set — that
        # bevel is the white edge. Flattening all three border colors to the
        # same value removes it instead of just recoloring it.
        style.configure(
            "Modern.TCombobox",
            background=Palette.FIELD,
            fieldbackground=Palette.FIELD,
            foreground=Palette.TEXT,
            selectbackground=Palette.FIELD,
            selectforeground=Palette.TEXT,
            arrowcolor=Palette.TEXT_MUTED,
            bordercolor=Palette.FIELD_BORDER,
            lightcolor=Palette.FIELD,
            darkcolor=Palette.FIELD,
            borderwidth=1,
            relief="flat",
            padding=8,
            arrowsize=13,
        )
        style.map(
            "Modern.TCombobox",
            fieldbackground=[("readonly", Palette.FIELD), ("focus", Palette.FIELD)],
            foreground=[("readonly", Palette.TEXT)],
            background=[("readonly", Palette.FIELD), ("active", Palette.FIELD)],
            bordercolor=[("focus", Palette.ACCENT), ("!focus", Palette.FIELD_BORDER)],
            lightcolor=[("focus", Palette.FIELD), ("!focus", Palette.FIELD)],
            darkcolor=[("focus", Palette.FIELD), ("!focus", Palette.FIELD)],
            arrowcolor=[("active", Palette.TEXT), ("!active", Palette.TEXT_MUTED)],
        )
        style.layout(
            "Modern.TCombobox",
            [("Combobox.field", {"sticky": "nswe", "children": [
                ("Combobox.downarrow", {"side": "right", "sticky": "ns"}),
                ("Combobox.padding", {"sticky": "nswe", "children": [
                    ("Combobox.textarea", {"sticky": "nswe"})
                ]}),
            ]})],
        )

        # The dropdown popdown list is a plain Tk Listbox — theme it too so
        # it doesn't flash white when opened.
        self.option_add("*TCombobox*Listbox.background", Palette.FIELD)
        self.option_add("*TCombobox*Listbox.foreground", Palette.TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", Palette.SURFACE_HOVER)
        self.option_add("*TCombobox*Listbox.selectForeground", Palette.TEXT)
        self.option_add("*TCombobox*Listbox.borderWidth", 0)
        self.option_add("*TCombobox*Listbox.highlightThickness", 1)
        self.option_add("*TCombobox*Listbox.highlightColor", Palette.FIELD_BORDER)
        self.option_add("*TCombobox*Listbox.highlightBackground", Palette.FIELD_BORDER)
        self.option_add("*TCombobox*Listbox.font", f"{{{Palette.FONT_FAMILY}}} 10")

    # ------------------------------------------------------------------
    def _section_label(self, parent, text):
        tk.Label(
            parent,
            text=text.upper(),
            bg=parent["bg"],
            fg=Palette.TEXT_FAINT,
            font=_font(9, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(0, 10))

    def _field_label(self, parent, text):
        tk.Label(
            parent,
            text=text,
            bg=parent["bg"],
            fg=Palette.TEXT_MUTED,
            font=_font(9),
            anchor="w",
        ).pack(anchor="w", pady=(0, 4))

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = tk.Frame(self, bg=Palette.BG)
        root.pack(fill="both", expand=True)

        # Header
        header = tk.Frame(root, bg=Palette.PANEL, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text="Always Online",
            bg=Palette.PANEL,
            fg=Palette.TEXT,
            font=_font(16, "bold"),
        ).place(x=24, y=18)

        tk.Label(
            header,
            text="account session manager",
            bg=Palette.PANEL,
            fg=Palette.TEXT_FAINT,
            font=_font(9),
        ).place(x=24, y=42)

        tk.Label(
            header,
            text=f"v{__version__}",
            bg=Palette.PANEL,
            fg=Palette.TEXT_FAINT,
            font=_font(9),
        ).place(relx=1.0, x=-24, y=28, anchor="e")

        divider = tk.Frame(root, bg=Palette.DIVIDER, height=1)
        divider.pack(fill="x")

        # Body
        content = tk.Frame(root, bg=Palette.BG)
        content.pack(fill="both", expand=True, padx=16, pady=12)

        left = tk.Frame(content, bg=Palette.BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right = tk.Frame(content, bg=Palette.BG)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        # --- Create account card ---------------------------------------
        create_outer = RoundedCard(left)
        create_outer.pack(fill="both", expand=True)
        create_card = create_outer.content

        self._section_label(create_card, "New Account")

        self._field_label(create_card, "Account name")
        self.name_entry = RoundedEntry(create_card, textvariable=self.name_var)
        self.name_entry.pack(fill="x", pady=(0, 8))

        self._field_label(create_card, "CSFloat URL")
        self.csfloat_entry = RoundedEntry(create_card, textvariable=self.csfloat_var)
        self.csfloat_entry.pack(fill="x", pady=(0, 8))

        self._field_label(create_card, "CSGOEmpire URL")
        self.csgoempire_entry = RoundedEntry(create_card, textvariable=self.csgoempire_var)
        self.csgoempire_entry.pack(fill="x", pady=(0, 8))

        RoundButton(
            create_card,
            "Create & Open",
            command=self.create_account_workflow,
            bg=Palette.ACCENT,
            hover=Palette.ACCENT_HOVER,
            fg=Palette.ACCENT_TEXT,
        ).pack(fill="x", pady=(0, 10))

        RoundButton(
            create_card,
            "Save Session",
            command=self.save_logged_in_session,
            bg=Palette.SURFACE,
            hover=Palette.SURFACE_HOVER,
            fg=Palette.TEXT,
        ).pack(fill="x")

        # --- Saved accounts card -----------------------------------------
        saved_outer = RoundedCard(right)
        saved_outer.pack(fill="both", expand=True)
        saved_card = saved_outer.content

        self._section_label(saved_card, "Saved Accounts")

        self._field_label(saved_card, "Select account")
        self.account_list = ttk.Combobox(saved_card, state="readonly", style="Modern.TCombobox")
        self.account_list.pack(fill="x", pady=(0, 12), ipady=4)

        RoundButton(
            saved_card,
            "Launch Selected",
            command=self.launch_selected,
            bg=Palette.ACCENT,
            hover=Palette.ACCENT_HOVER,
            fg=Palette.ACCENT_TEXT,
        ).pack(fill="x", pady=(0, 10))

        RoundButton(
            saved_card,
            "Launch All",
            command=self.launch_all_accounts,
            bg=Palette.SURFACE,
            hover=Palette.SURFACE_HOVER,
            fg=Palette.TEXT,
        ).pack(fill="x", pady=(0, 10))

        RoundButton(
            saved_card,
            "Test",
            command=self.test_activity,
            bg=Palette.SURFACE,
            hover=Palette.SURFACE_HOVER,
            fg=Palette.TEXT,
        ).pack(fill="x", pady=(0, 10))

        RoundButton(
            saved_card,
            "Refresh",
            command=self.refresh_account_list,
            bg=Palette.SURFACE,
            hover=Palette.SURFACE_HOVER,
            fg=Palette.TEXT,
        ).pack(fill="x", pady=(0, 10))

        RoundButton(
            saved_card,
            "Kill All",
            command=self.kill_all_accounts,
            bg=Palette.DANGER,
            hover=Palette.DANGER_HOVER,
            fg=Palette.DANGER_TEXT,
        ).pack(fill="x")

        # Status bar
        status_divider = tk.Frame(root, bg=Palette.DIVIDER, height=1)
        status_divider.pack(fill="x", side="bottom")

        status_bar = tk.Frame(root, bg=Palette.BG)
        status_bar.pack(fill="x", side="bottom")

        tk.Label(
            status_bar,
            textvariable=self.status_var,
            bg=Palette.BG,
            fg=Palette.TEXT_MUTED,
            font=_font(9),
            justify="left",
            anchor="w",
            wraplength=940,
        ).pack(side="left", fill="x", expand=True, padx=(24, 12), pady=14)

        tk.Label(
            status_bar,
            textvariable=self.launch_timer_var,
            bg=Palette.BG,
            fg=Palette.TEXT_MUTED,
            font=_font(9),
            anchor="w",
        ).pack(side="left", padx=(0, 24), pady=14)

    # ------------------------------------------------------------------
    def refresh_account_list(self):
        names = account_store.list_names()
        self.account_list["values"] = names
        if names:
            self.account_list.set(names[0])
        else:
            self.account_list.set("")

    def create_account_workflow(self):
        name = (self.name_var.get() or "").strip()
        csfloat_url = self.csfloat_var.get().strip()
        csgoempire_url = self.csgoempire_var.get().strip()
        if not name:
            messagebox.showerror("Missing account name", "Please enter an account name before creating the profile.")
            return

        try:
            account = create_account_record(name, csfloat_url, csgoempire_url)
            proc = launch_account_record(account, large=True)

            save_choice = messagebox.askyesno(
                "Save account?",
                f"Save account '{account.name}' and keep the browser profiles?\n\nClick 'Yes' to keep it, or 'No' to close the browsers and delete this account.",
                default="yes",
            )
            if save_choice:
                save_current_session_and_keep(account)
                self.status_var.set(
                    f"Account '{account.name}' opened. Log in to both sites, then click 'Save Session' when you are finished."
                )
            else:
                close_browser_processes(proc)
                account_store.delete(account.name, remove_browser_profiles=True)
                self.status_var.set(f"Account '{account.name}' was discarded and deleted.")

            self.name_var.set("")
            self.refresh_account_list()
        except (AccountValidationError, ValueError) as exc:
            self.status_var.set(str(exc))
            messagebox.showerror("Create account failed", str(exc))

    def _finish_new_account(self, account: Account, proc) -> None:
        if messagebox.askyesno(
            "Are you done?",
            "You are logged in. Do you want to close the browser windows and keep this account session?",
            default="no",
        ):
            if confirm_done_and_save(account, True, proc):
                self.status_var.set(f"Account '{account.name}' saved and browser windows closed.")
        else:
            close_browser_processes(proc)
            account_store.delete(account.name, remove_browser_profiles=True)
            self.refresh_account_list()
            self.status_var.set(f"Account '{account.name}' discarded. Browser profiles and local account data were deleted.")

    def save_logged_in_session(self):
        name = (self.name_var.get() or "").strip() or self.account_list.get()
        if not name:
            messagebox.showinfo("No account selected", "Create an account first or pick one from the saved list.")
            return

        try:
            account = account_store.load(name)
        except Exception:
            account = create_account_record(name, self.csfloat_var.get().strip(), self.csgoempire_var.get().strip())

        account.csfloat_url = self.csfloat_var.get().strip()
        account.csgoempire_url = self.csgoempire_var.get().strip()
        save_current_session_and_keep(account)
        self.status_var.set(
            f"Session saved for '{account.name}'. The browser profile folders are stored under browser_profiles/{account.name}/ and are ready to launch again."
        )
        self.refresh_account_list()

    def launch_all_accounts(self):
        names = account_store.list_names()
        if not names:
            self.status_var.set("No saved accounts to launch.")
            self.launch_timer_var.set("Next launch: --")
            return

        if self._launch_sequence_running:
            self.status_var.set("A sequential launch is already in progress.")
            return

        launched: list[str] = []
        launch_batch_started_at = time.time()
        all_active_deadline = time.monotonic() + 10 * 60
        self._launch_sequence_running = True
        self.status_var.set(f"Starting sequential launch of {len(names)} account(s) with 70-second intervals...")

        def notify_all_active():
            asyncio.run(
                DiscordNotifier().notify_all_sessions_active(
                    account_count=len(names),
                    session_count=len(names) * 2,
                )
            )

        def wait_for_all_active():
            """Wait for fresh results from this launch batch before notifying."""
            all_healthy = True
            for account_name in names:
                try:
                    account = account_store.load(account_name)
                except Exception:
                    all_healthy = False
                    break
                for site in (Site.CSFLOAT, Site.CSGOEMPIRE):
                    state = account.site_state(site)
                    if state.last_checked < launch_batch_started_at or state.state != "healthy":
                        all_healthy = False
                        break
                if not all_healthy:
                    break

            if all_healthy:
                threading.Thread(target=notify_all_active, daemon=True).start()
            elif time.monotonic() < all_active_deadline:
                self.after(5_000, wait_for_all_active)

        def update_timer():
            if not self._launch_sequence_running or self._launch_deadline is None:
                self._launch_timer_after_id = None
                self.launch_timer_var.set("Next launch: --")
                return
            remaining = max(0, int(self._launch_deadline - time.monotonic() + 0.999))
            self.launch_timer_var.set(f"Next launch: {remaining // 60}:{remaining % 60:02d}")
            self._launch_timer_after_id = self.after(1000, update_timer)

        def on_launch(name, index):
            self.status_var.set(f"Launched {name} ({index + 1}/{len(names)}).")
            if index + 1 < len(names):
                self._launch_deadline = time.monotonic() + LAUNCH_INTERVAL_MS / 1000
                if self._launch_timer_after_id is None:
                    update_timer()
            else:
                self._launch_sequence_running = False
                self._launch_deadline = None
                self.launch_timer_var.set("Next launch: --")
                self.status_var.set(f"Sequential launch complete. {len(launched)} account(s) launched.")
                self.after(5_000, wait_for_all_active)

        def on_error(name, exc, index):
            self.status_var.set(f"Launch failed for {name}: {exc}")
            if index + 1 < len(names):
                self._launch_deadline = time.monotonic() + LAUNCH_INTERVAL_MS / 1000
                if self._launch_timer_after_id is None:
                    update_timer()
            else:
                self._launch_sequence_running = False
                self._launch_deadline = None
                self.launch_timer_var.set("Next launch: --")

        launch_all_accounts_sequential(self, names, launched, on_launch=on_launch, on_error=on_error)
        if len(names) == 1:
            self._launch_sequence_running = False

    def kill_all_accounts(self):
        killed = kill_all_accounts()
        if not killed:
            self.status_var.set("No active account processes to kill.")
            return
        self.status_var.set(f"Closed {len(killed)} account process(es): {', '.join(killed)}")

    def test_activity(self):
        tested = test_active_account_activity()
        if not tested:
            self.status_var.set("No active account browsers to test.")
            return
        self.status_var.set(f"Randomized scroll test sent to {len(tested)} account(s): {', '.join(tested)}")

    def launch_selected(self):
        name = self.account_list.get()
        if not name:
            messagebox.showinfo("No account selected", "Create an account first or select one from the saved list.")
            return

        try:
            # Launch single account at position 0 (top-left)
            launch_account_by_name(name, large=False, launch_sequence_index=0)
            self.status_var.set(f"Launching saved account: {name}")
        except Exception as exc:  # pragma: no cover - display to user
            self.status_var.set(f"Launch failed: {exc}")
            messagebox.showerror("Launch failed", str(exc))


def main():
    app = AccountManagerGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
