"""Self-check: the claims the design rests on, measured rather than assumed.

Run: .venv\\Scripts\\python.exe -m deskweft.check
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
$f.Text = "DESKWEFT-CHECK"
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
        if w["title"].startswith("DESKWEFT-CHECK") and w["pid"] == pid:
            return w["hwnd"]
    return None


def _window_pid(hwnd: int) -> int:
    """The process that owns a window, for proving a handle is still ours."""
    import ctypes
    from ctypes import wintypes

    pid = wintypes.DWORD()
    win32.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _close_owned(result: dict) -> None:
    """Close only the windows a launch proved it owns, by pid."""
    pids = {result.get("pid")}
    pids.update(w["pid"] for w in result.get("hidden_windows", []))
    for item in result.get("hidden_windows", []):
        hwnd = item["hwnd"]
        if item.get("pid") in pids and win32.user32.IsWindow(hwnd):
            win32.user32.PostMessageW(hwnd, 0x0010, 0, 0)


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
    workdir = tempfile.mkdtemp(prefix="deskweft-check-")
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
        detailed = tree.read_detailed(hwnd, timeout_ms=3000)
        elements = detailed["elements"]
        dt = (time.perf_counter() - t0) * 1000
        names = [e["name"] for e in elements]
        check("tree.read() finds the button", "HIT-ME" in names, f"{dt:.0f} ms, {len(elements)} elements")
        check("tree.read() leaves the foreground alone", win32.foreground() == fg)
        check("read_detailed() reports a complete read",
              detailed["identity_complete"] and not detailed["timed_out"]
              and detailed["tree_diagnostics"]["root_status"] == "ok",
              str(detailed["tree_diagnostics"].get("root_status")))
        button = next((e for e in elements if e["name"] == "HIT-ME"), None)
        check("describe() carries the native child handle",
              bool(button and button["native_hwnd"]), str(button and button["native_hwnd"]))
        check("the pattern guard explains an unwrapped pattern",
              tree.pattern_detailed(button["_el"] if button else None,
                                    "SelectionPattern2").get("reason")
              == "pattern not wrapped")
        check("the pattern guard keeps cause_unknown for a None wrapper",
              tree.pattern_detailed(button["_el"] if button else None,
                                    "WindowPattern").get("cause_unknown", True) is not False)

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

        # The window was made by another process, which is what the same-process
        # rule in post_message exists to allow.
        edit = next((k for k in win32.children(hwnd) if "Edit" in k["class"]), None)
        if edit:
            got = win32.post_message(edit["hwnd"], 0x000E, wait=True)
            check("post_message WM_GETTEXTLENGTH returns a length",
                  got.get("ok") is True and isinstance(got.get("result"), int),
                  str(got.get("reason", "")))
            text = win32.post_message(edit["hwnd"], 0x000D, wait=True, max_chars=256)
            check("post_message WM_GETTEXT reads managed text", text.get("ok") is True,
                  repr(text.get("text")))
            wrote = win32.post_message(edit["hwnd"], 0x000C, wait=True, text="by message",
                                       allow_foreground=True)
            check("post_message WM_SETTEXT verifies its own readback",
                  wrote.get("ok") is True and wrote.get("effect_verified") is True,
                  f"{wrote.get('reason')} / {wrote.get('verification_reason')}")
            check("post_message leaves the foreground alone",
                  wrote.get("foreground_changed") is False)
            # A caller asking for the write without permission must be refused
            # before anything is sent, and the refusal names permission.
            denied = win32.post_message(edit["hwnd"], 0x000C, wait=True, text="x")
            check("post_message gates a setter behind permission",
                  denied.get("needs_permission") is True,
                  f"{denied.get('reason')}: {denied.get('detail')}")
            click_denied = win32.post_message(edit["hwnd"], 0x00F5, wait=False)
            check("post_message gates a queued click behind permission",
                  click_denied.get("needs_permission") is True,
                  str(click_denied.get("reason")))
            unsafe = win32.post_message(edit["hwnd"], 0x004A, wait=True,
                                        allow_unsafe=True, allow_foreground=True)
            check("post_message refuses an unmanaged payload",
                  unsafe.get("reason") == "message payload unsupported", str(unsafe.get("reason")))

        # Memory: a temporary root, so the user's real records are untouched.
        from . import memory

        import tempfile as _tempfile

        with _tempfile.TemporaryDirectory(prefix="deskweft-mem-") as memdir:
            from pathlib import Path as _Path
            from unittest import mock as _mock

            with _mock.patch.object(memory, "memory_root", return_value=_Path(memdir)):
                stored = memory.remember(
                    "check", "1.0", "A", "summary", "cost",
                    "## \u76ee\u6807\nx\n## \u672a\u89e3\u51b3\nstill open\n",
                    uses_foreground=False)
                check("memory stores a plan", stored.get("ok") is True, str(stored.get("reason")))
                found = memory.recall("check@1.0")
                check("memory recalls it with a revision",
                      bool(found["matches"]) and bool(
                          found["matches"][0]["plans"][0]["revision"]))
                check("memory derives the unresolved gap",
                      memory.unresolved()[0]["text"] == "still open")
                stale = memory.approve("check", "1.0", "A", "not-the-revision")
                check("memory refuses a stale approval",
                      stale.get("reason") == "stale plan", str(stale.get("reason")))

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
        fg_title_before = win32.title(fg_before)
        res = launch.launch("notepad.exe", settle=2.0)
        check("launch() started the program", res.get("ok") is True and res.get("pid"), str(res.get("reason", "")))

        # A single-instance app hands the work to an already running copy, so
        # the launched process owns no window. Ownership then has to come out
        # unconfirmed - and the foreground may legitimately have moved to that
        # other instance, which this run never claimed.
        handover = res.get("visibility_control") == "unconfirmed"
        if handover:
            # A single-instance app handed the work to an already running copy:
            # this run owns no window, so it must claim none - and acting on the
            # other instance's window would be exactly the guess to avoid.
            check("launch() refused to claim a window it could not attribute",
                  res.get("target_window_confirmed") is False
                  and res.get("hidden_windows") == [],
                  f"visibility_control={res.get('visibility_control')}")
        else:
            check("launch() kept the foreground", win32.foreground() == fg_before,
                  f"{win32.title(win32.foreground())[:30]!r}")
            check("launch() hid the new window", len(res.get("hidden_windows", [])) > 0)

        # Only windows this run proved it owns may be closed afterwards: the
        # machine may already be running the user's own Notepad.
        launched_pids = {res.get("pid")}
        launched_pids.update(w["pid"] for w in res.get("hidden_windows", []))
        hidden = [w["hwnd"] for w in res.get("hidden_windows", [])]
        # A launch reports every owned window, including IME and input sites
        # that have no editor. Pick the one that actually carries a text control
        # instead of assuming the first.
        editor_owner = next(
            (hwnd for hwnd in hidden
             if any("RICHEDIT" in k["class"].upper() for k in win32.children(hwnd))),
            None)
        if editor_owner is not None:
            r = act.act(editor_owner, "type", target="RICHEDIT", text="hidden write")
            kids = [k for k in win32.children(editor_owner)
                    if "RICHEDIT" in k["class"].upper()]
            got = (win32.post_message(kids[0]["hwnd"], 0x000D, wait=True,
                                      max_chars=4096).get("text") if kids else None)
            check("a hidden window still accepts text",
                  r.get("ok") is True and got == "hidden write", repr(got))
        else:
            # Either this Notepad is single-instance and handed the work to an
            # already running copy (so no window belongs to the process this run
            # started), or every owned window is an input site with no editor.
            # Both are honest outcomes, and neither is proof that typing failed.
            print(f"  SKIP  a hidden window still accepts text"
                  f"  (visibility_control={res.get('visibility_control')}, "
                  f"{len(hidden)} owned window(s), none with an editor)")
            check("launch() never claims a window it cannot attribute",
                  res.get("target_window_confirmed") in (True, False)
                  and (bool(hidden) == bool(res.get("target_window_confirmed"))))

        # Notepad may be single-instance, so prove the owned-window path on an
        # app that really starts a new process.
        fresh = r"C:\Windows\System32\charmap.exe"
        if os.path.exists(fresh) and not any("Character Map" in w["title"]
                                             for w in win32.list_windows()):
            fg = win32.foreground()
            owned = launch.launch(fresh, settle=2.5)
            if owned.get("visibility_control") == "applied":
                hidden_ok = all(w["hide_succeeded"] and w["ownership_basis"] == "direct_process"
                                for w in owned["hidden_windows"])
                check("a proven new process has its own windows hidden",
                      hidden_ok and owned["target_window_confirmed"] is True,
                      f"{len(owned['hidden_windows'])} windows")
                check("hiding them kept the foreground", win32.foreground() == fg,
                      f"{win32.title(win32.foreground())[:30]!r}")
                check("no unrelated window was claimed", owned["window_candidates"] == [],
                      str(len(owned["window_candidates"])))
            else:
                check("a proven new process has its own windows hidden",
                      owned.get("visibility_control") == "unconfirmed",
                      f"visibility_control={owned.get('visibility_control')}")
            _close_owned(owned)

        # Close only what this run started, verified by pid: a class-name scan
        # would close every Notepad on the machine.
        for hwnd in hidden:
            pid = _window_pid(hwnd)
            if pid and pid in launched_pids and win32.user32.IsWindow(hwnd):
                win32.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        for w in win32.list_windows():
            if ("Notepad" in w["class"] or "Notepad" in w["title"]) and w["pid"] in launched_pids:
                win32.user32.PostMessageW(w["hwnd"], 0x0010, 0, 0)
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
