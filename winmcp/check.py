"""Self-check: the claims the design rests on, measured rather than assumed.

Run: .venv\\Scripts\\python.exe -m winmcp.check
It builds its own window, so it never touches your real windows.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

from . import act, tree, win32

APP = r"""
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object System.Windows.Forms.Form
$f.Text = "WINMCP-CHECK"
$f.Width = 460
$f.Height = 320
$b = New-Object System.Windows.Forms.Button
$b.Text = "HIT-ME"
$b.Left = 30; $b.Top = 30; $b.Width = 170; $b.Height = 55
$f.Controls.Add($b)
$t = New-Object System.Windows.Forms.TextBox
$t.Text = "initial"
$t.Left = 30; $t.Top = 105; $t.Width = 360
$f.Controls.Add($t)
$l = New-Object System.Windows.Forms.Label
$l.Text = "clicks:0"
$l.Left = 30; $l.Top = 160; $l.Width = 300
$f.Controls.Add($l)
$b.Add_Click({
  $n = [int]($l.Text.Split(":")[1]) + 1
  $l.Text = "clicks:$n"
})
$f.ShowDialog()
"""

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")


def find_check_window(pid: int) -> int | None:
    """Only our own window: a stale one from an earlier run would answer too."""
    for w in win32.list_windows():
        if w["title"].startswith("WINMCP-CHECK") and w["pid"] == pid:
            return w["hwnd"]
    return None


def read_label(hwnd: int) -> str | None:
    """Click feedback lives in a Label; UIA is the only cross-process view."""
    for e in tree.read(hwnd, timeout_ms=3000)[0]:
        if e["control_type"] == "TextControl" and e["name"].startswith("clicks:"):
            return e["name"]
    return None


def read_edit(hwnd: int) -> str | None:
    for e in tree.read(hwnd, timeout_ms=3000)[0]:
        if e["control_type"] == "EditControl":
            vp = tree.pattern(e["_el"], "ValuePattern")
            return vp.Value if vp else None
    return None


def main() -> int:
    # Run the test window inside its own temp dir: pwsh drops tmp*.ps1 next to
    # whatever the working directory is, and that debris must not land in the
    # project.
    workdir = tempfile.mkdtemp(prefix="winmcp-check-")
    script = os.path.join(workdir, "app.ps1")
    with open(script, "w", encoding="utf-8") as f:
        f.write(APP)
    proc = subprocess.Popen(
        ["pwsh", "-NoProfile", "-WindowStyle", "Hidden", "-File", script],
        creationflags=subprocess.CREATE_NO_WINDOW,
        cwd=workdir,
    )
    try:
        hwnd = None
        for _ in range(40):
            time.sleep(0.25)
            hwnd = find_check_window(proc.pid)
            if hwnd:
                break
        if not hwnd:
            print("could not create the check window")
            return 1

        print("checking against a window it just made, not yours\n")

        t0 = time.perf_counter()
        wins = win32.list_windows()
        check("windows() is cheap", (time.perf_counter() - t0) * 1000 < 200, f"{len(wins)} windows")

        fg = win32.foreground()
        grabbed = win32.grab(hwnd)
        check("grab() returns a real frame", grabbed is not None, str(grabbed[1:]) if grabbed else "")
        check("grab() leaves the foreground alone", win32.foreground() == fg)

        fg = win32.foreground()
        t0 = time.perf_counter()
        elements, timed_out = tree.read(hwnd, timeout_ms=3000)
        dt = (time.perf_counter() - t0) * 1000
        names = [e["name"] for e in elements]
        check("tree.read() finds the button", "HIT-ME" in names, f"{dt:.0f} ms, {len(elements)} elements")
        check("tree.read() leaves the foreground alone", win32.foreground() == fg)

        fg = win32.foreground()
        r = act.act(hwnd, "click", target="HIT-ME")
        time.sleep(0.6)
        check("click() used a window message", r.get("route") == "win32:BM_CLICK", str(r.get("route")))
        check("click() reported no foreground change", r.get("foreground_changed") is False)
        check("click() actually landed", read_label(hwnd) == "clicks:1", str(read_label(hwnd)))
        check("click() left the foreground alone", win32.foreground() == fg)

        fg = win32.foreground()
        r = act.act(hwnd, "type", target="initial", text="typed \u4e2d\u6587")
        check("type() used a window message", r.get("route") == "win32:WM_SETTEXT", str(r.get("route")))
        check("type() reported no foreground change", r.get("foreground_changed") is False)
        check("type() wrote Unicode correctly", read_edit(hwnd) == "typed \u4e2d\u6587", repr(read_edit(hwnd)))
        check("type() left the foreground alone", win32.foreground() == fg)

        # Real editors (Notepad's RichEditD2DPT among them) carry no title text,
        # so a text-only match could never find them. Addressing by class has to
        # work for an untitled editor.
        untitled = [k for k in win32.children(hwnd) if "Edit" in k["class"]]
        if untitled:
            fg = win32.foreground()
            r = act.act(hwnd, "type", target=untitled[0]["class"], text="by class")
            check("type() can address an untitled editor by class", r.get("ok") is True, str(r.get("reason", "")))
            check("class-addressed write left the foreground alone", win32.foreground() == fg)
            check("class-addressed write actually landed", read_edit(hwnd) == "by class", repr(read_edit(hwnd)))

        fg = win32.foreground()
        r = act.act(hwnd, "key", text="Ctrl+s")
        check("key() refuses without permission", r.get("needs_permission") is True)
        check("key() did not touch the foreground", win32.foreground() == fg)
        check("refusal explains itself", bool(r.get("hint")))

        r = act.act(hwnd, "click", target="no-such-control")
        check("an unroutable click asks instead of acting", r.get("needs_permission") is True)

        # Render hosts and D3D windows answer PostMessage with success and do
        # nothing. Clicking one must be refused, never reported as done.
        false_positive = None
        for label, target in (
            ("Chrome render host", "Chrome Legacy Window"),
            ("D3D window", "Intermediate D3D Window"),
        ):
            for w in win32.list_windows():
                if any(k["text"] == target for k in win32.children(w["hwnd"])):
                    res = act.act(w["hwnd"], "click", target=target)
                    if res.get("ok"):
                        false_positive = f"{w['title'][:20]} / {label} -> {res.get('route')}"
                    break
            if false_positive:
                break
        check("a non-button child is never clicked as if it were a button", false_positive is None, false_positive or "")

        # Typing must never claim success when the field stayed empty. A
        # browser input accepts SetValue silently and keeps nothing; the old
        # code reported cursor:keys and the submitted form arrived blank.
        empty = act.act(hwnd, "type", target="no-such-field", text="x")
        check("type() on a missing control fails loudly", empty.get("ok") is False, str(empty.get("reason", "")))

        r = act.act(999999999, "click", target="whatever")
        check("dead hwnd reports no such window", r.get("ok") is False)

        # An invalid handle used to escape as a COMError, which reaches the
        # client as a server failure instead of an answer.
        for bad in (0, -1, 1, 2**31 - 1):
            try:
                els, _to = tree.read(bad, timeout_ms=200)
                check(f"tree.read({bad}) returns empty, not an exception", els == [], str(len(els)))
            except Exception as e:
                check(f"tree.read({bad}) returns empty, not an exception", False, f"{type(e).__name__}")

        # Plain text containing "+" is text, not a chord: "1+1" once became
        # "{1}{1}" and typed "11".
        from .act import _normalise_keys

        for text in ("1+1", "a+b", "x+y+z", "2 + 2"):
            got = _normalise_keys(text)
            check(f"plus signs survive: {text!r}", got == text, repr(got))

        # Key notation must be translated, not typed literally. "^s" reaching
        # SendKeys as raw text once wrote ^s into a real document.
        from .act import _normalise_keys

        pairs = {
            "^s": "{Ctrl}{s}",
            "Ctrl+s": "{Ctrl}{s}",
            "Ctrl+Shift+s": "{Ctrl}{Shift}{s}",
            "^{END}": "{Ctrl}{END}",
            "Enter": "{Enter}",
            "hello world": "hello world",
            "{Enter}": "{Enter}",
        }
        bad = {k: _normalise_keys(k) for k, v in pairs.items() if _normalise_keys(k) != v}
        check("key notation is translated, not typed literally", not bad, str(bad))

        # Launching must not steal the foreground. This was the user's actual
        # complaint: starting an app popped its window in front of them.
        from . import launch

        fg_before = win32.foreground()
        res = launch.launch("notepad.exe", settle=2.0)
        check("launch() started the program", res.get("ok") is True and res.get("pid"), str(res.get("reason", "")))
        check("launch() kept the foreground", win32.foreground() == fg_before,
              f"{win32.title(win32.foreground())[:30]!r}")
        check("launch() hid the new window", len(res.get("hidden_windows", [])) > 0)

        hidden = [w["hwnd"] for w in res.get("hidden_windows", [])]
        if hidden:
            r = act.act(hidden[0], "type", target="RICHEDIT", text="hidden write")
            from windows_mcp.uia import ControlFromHandle

            kids = [k for k in win32.children(hidden[0]) if "RICHEDIT" in k["class"].upper()]
            got = ControlFromHandle(kids[0]["hwnd"]).GetValuePattern().Value if kids else None
            check("a hidden window still accepts text", r.get("ok") is True and got == "hidden write", repr(got))

        for w in win32.list_windows():
            if "Notepad" in w["class"]:
                win32.user32.PostMessageW(w["hwnd"], 0x0010, 0, 0)
        for h in hidden:
            win32.user32.PostMessageW(h, 0x0010, 0, 0)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(workdir, ignore_errors=True)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
