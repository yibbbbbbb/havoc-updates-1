"""Edit the public daily message and its UTC schedule; preview drafts in the real desktop UI."""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from message_schedule import message_text, parse_message_feed

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "public/desktop/daily-message.json"


def preview(skin, text):
    with TemporaryDirectory(prefix="havoc-message-preview-") as tmp:
        path = Path(tmp) / "HavocMidnight.py"
        shutil.copyfile(ROOT / "public/desktop/HavocMidnight.py", path)
        spec = importlib.util.spec_from_file_location("havoc_preview", path)
        desktop = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(desktop)
        desktop.ROOT = Path(tmp)
        desktop.ASSET_ROOT = desktop.ROOT / "assets"
        desktop.Panel.default_layout = skin
        desktop.WINDOW_TITLE = "Announcement preview · " + skin
        desktop.DEFAULT_DAILY_MESSAGE = message_text(text)
        desktop.DailyMessage.poll = lambda self: None
        desktop.prepare_assets()
        desktop.main()


def edit():
    import tkinter as tk
    from tkinter import messagebox, ttk

    win = tk.Tk()
    win.title("Havoc · Announcement schedule")
    win.columnconfigure(0, weight=1)
    win.rowconfigure(1, weight=1)
    original = FEED.read_bytes()
    feed = json.loads(original)
    parse_message_feed(feed)
    rows = list(feed.get("schedule", []))
    fallback = tk.StringVar(value=feed["message"])
    form = ttk.Frame(win, padding=12)
    form.grid(sticky="ew")
    form.columnconfigure(1, weight=1)
    ttk.Label(form, text="Default message").grid(row=0, column=0, padx=4)
    ttk.Entry(form, textvariable=fallback, width=52).grid(row=0, column=1, sticky="ew")
    table = ttk.Treeview(
        win,
        columns=("start", "end", "message"),
        show="headings",
        height=7,
        selectmode="browse",
    )
    table.grid(row=1, column=0, sticky="nsew", padx=12)
    for key, label, width in (
        ("start", "Starts (UTC)", 160),
        ("end", "Expires (UTC)", 160),
        ("message", "Message", 340),
    ):
        table.heading(key, text=label)
        table.column(key, width=width)
    box = ttk.Frame(win, padding=12)
    box.grid(row=2, column=0, sticky="ew")
    box.columnconfigure(1, weight=1)
    now = datetime.now(timezone.utc).replace(microsecond=0, second=0)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    fields = {
        k: tk.StringVar(value=v)
        for k, v in (
            ("start", now.strftime(fmt)),
            ("end", (now + timedelta(days=1)).strftime(fmt)),
            ("message", ""),
        )
    }
    for n, (key, value) in enumerate(fields.items()):
        ttk.Label(
            box,
            text={
                "start": "Starts (UTC)",
                "end": "Expires (UTC)",
                "message": "Message",
            }[key],
        ).grid(row=n, column=0, sticky="w")
        ttk.Entry(box, textvariable=value).grid(row=n, column=1, sticky="ew")

    def repaint():
        for item in table.get_children():
            table.delete(item)
        for i, row in enumerate(rows):
            table.insert("", "end", iid=str(i), values=tuple(row[k] for k in fields))

    def selected(_event):
        if table.selection():
            row = rows[int(table.selection()[0])]
            for k, v in fields.items():
                v.set(row[k])

    def queue():
        row = {k: v.get().strip() for k, v in fields.items()}
        updated = rows.copy()
        if table.selection():
            updated[int(table.selection()[0])] = row
        else:
            updated.append(row)
        parse_message_feed({"message": fallback.get(), "schedule": updated})
        rows[:] = sorted(updated, key=lambda r: r["start"])
        repaint()

    def remove():
        if table.selection():
            rows.pop(int(table.selection()[0]))
            repaint()

    def save():
        nonlocal original
        doc = {"message": fallback.get(), "schedule": rows}
        parse_message_feed(doc)
        if FEED.read_bytes() != original:
            raise ValueError(
                "The source changed on disk. Reopen the editor to load it."
            )
        data = (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode()
        with NamedTemporaryFile(dir=FEED.parent, delete=False) as out:
            stage = Path(out.name)
        try:
            stage.write_bytes(data)
            os.chmod(stage, FEED.stat().st_mode & 0o777)
            os.replace(stage, FEED)
        finally:
            stage.unlink(missing_ok=True)
        original = data
        status.set(
            "Saved locally. Publish the Pages site to send this schedule to desktops."
        )

    def show(skin):
        text = message_text(fields["message"].get() or fallback.get())
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--preview", skin, text]
        )

    def action(fn):
        def run():
            try:
                fn()
            except (ValueError, OSError) as exc:
                messagebox.showerror("Announcement schedule", str(exc), parent=win)

        return run

    buttons = ttk.Frame(box)
    buttons.grid(row=3, columnspan=2, pady=6)
    for label, fn in (
        (
            "New",
            lambda: (
                table.selection_remove(*table.selection()),
                fields["message"].set(""),
            ),
        ),
        ("Queue / replace", queue),
        ("Remove selected", remove),
        ("Preview Midnight", lambda: show("Midnight")),
        ("Preview Classic", lambda: show("Classic")),
        ("Save schedule", save),
    ):
        ttk.Button(buttons, text=label, command=action(fn)).pack(side="left", padx=2)
    status = tk.StringVar(value="Enter UTC times, then queue the draft before saving.")
    ttk.Label(box, textvariable=status).grid(row=4, columnspan=2, sticky="w")
    table.bind("<<TreeviewSelect>>", selected)
    repaint()
    win.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", nargs=2, metavar=("LAYOUT", "MESSAGE"))
    args = parser.parse_args()
    if args.preview:
        if args.preview[0] not in ("Classic", "Midnight"):
            parser.error("Choose Classic or Midnight")
        preview(*args.preview)
    else:
        edit()
