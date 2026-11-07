"""Drive a window without taking the foreground.

Two tiers, and the tier is decided by evidence, not by hope:

  tier 1  Win32 messages to a native child HWND. Measured: 0.0 ms, foreground
          unchanged. Always allowed, and the result is verified by reading the
          control back where a readback exists.
  tier 2  everything else - UIA pattern calls and real cursor input. Measured:
          UIA InvokePattern moved the foreground to the window (504-518 ms per
          call) on this machine. Never allowed without allow_foreground=True,
          and the caller must have the user's permission first.
"""

from __future__ import annotations

import ctypes
import time

from windows_mcp.uia import Click, ControlFromHandle, SendKeys, SetCursorPos, SetForegroundWindow

from . import tree, win32

BM_CLICK = 0x00F5
WM_SETTEXT = 0x000C
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202

# Only classes that are really pressable accept BM_CLICK. Anything else - a
# render host, a D3D window, a composition surface - reports success from
# PostMessage and does nothing, which is worse than refusing.
_BUTTON_CLASSES = ("Button", "msctls_", "ToolbarWindow32", "SSTabCtlWndClass", "SHELLDLL")
# Class tokens that can hold text a message can write. WinForms names its
# classes WindowsForms10.Edit..., so match anywhere in the class string.
_TEXT_CLASSES = ("Edit", "RICHEDIT", "Scintilla", "ComboBox")


def _needs_permission(reason: str, detail: str) -> dict:
    return {
        "ok": False,
        "needs_permission": True,
        "reason": reason,
        "detail": detail,
        "hint": "Show this to the user. Retry with allow_foreground=true only after they agree.",
    }


def _child(hwnd: int, target: str, classes: tuple[str, ...]) -> dict | None:
    """A native child of one of the allowed classes.

    `target` matches, in order: exact window text, substring of window text,
    then the class name. The class fallback matters because edit controls
    usually carry no title text at all, so there was nothing to match on.
    """
    kids = [k for k in win32.children(hwnd) if any(c.casefold() in k["class"].casefold() for c in classes)]
    if not kids:
        return None
    if not target:
        # A single unambiguous editor is what the caller meant.
        return kids[0] if len(kids) == 1 else None

    for k in kids:
        if k["text"] == target:
            return k
    low = target.casefold()
    for k in kids:
        if k["text"] and low in k["text"].casefold():
            return k
    for k in kids:
        if low in k["class"].casefold():
            return k
    return None


def _read_text(child_hwnd: int) -> str | None:
    """Current text of a control, read through UIA (works across processes)."""
    try:
        el = ControlFromHandle(child_hwnd)
        vp = el.GetValuePattern() if el is not None else None
        if vp is not None:
            return vp.Value
    except Exception:
        pass
    try:
        return win32.title(child_hwnd)
    except Exception:
        return None


def _normalise_keys(keys: str) -> str:
    """Turn a human key notation into the SendKeys format the UIA layer wants.

    SendKeys wants {Ctrl}s and {Enter}; a caller writing ^s or Ctrl+s would have
    those characters typed literally, silently mangling the document. Accept
    both spellings and emit the form that actually presses keys.
    """
    if not keys:
        return keys

    # ^s / ^{END} / %{F4}: classic notation, Ctrl/Alt apply to what follows.
    if keys[0] == "^":
        return "{Ctrl}" + _one_key(keys[1:].strip("{}"))
    if keys[0] == "%":
        return "{Alt}" + _one_key(keys[1:].strip("{}"))

    if "{" in keys:
        return keys  # already in SendKeys form, trust the caller

    parts = keys.split("+")
    if len(parts) > 1 and _looks_like_chord(parts):
        *mods, key = parts
        mods = [m.strip() for m in mods]
        return "".join("{%s}" % m for m in mods) + _one_key(key.strip())

    return _one_key(keys)


_MODIFIERS = {
    "CTRL", "CONTROL", "SHIFT", "ALT", "WIN", "LWIN", "RWIN",
    "LCTRL", "RCTRL", "LSHIFT", "RSHIFT", "LALT", "RALT",
}


def _looks_like_chord(parts: list[str]) -> bool:
    """Is "A+B" a key chord, or just text containing a plus sign?

    "ctrl+s" is a chord. "1+1" and "a+b" are text - treating them as chords
    drops the plus and types "{1}{1}". A chord is only a chord when every part
    before the last is a modifier name.
    """
    mods, key = parts[:-1], parts[-1].strip()
    if not key:
        return False
    return all(m.strip().upper() in _MODIFIERS for m in mods)


def _one_key(key: str) -> str:
    """Brace a single named key; leave ordinary text alone."""
    if not key:
        return key
    named = {
        "ENTER", "RETURN", "TAB", "ESC", "ESCAPE", "SPACE", "BACK", "DELETE", "DEL",
        "HOME", "END", "LEFT", "RIGHT", "UP", "DOWN", "PAGEUP", "PAGEDOWN",
        "INSERT", "INS", "APPS", "SLEEP",
    }
    upper = key.upper()
    if upper in named or (len(key) >= 2 and upper[0] == "F" and upper[1:].isdigit()):
        return "{%s}" % key
    if len(key) > 1 and key.isprintable():
        return key  # ordinary text; braced text would be sent literally anyway
    return "{%s}" % key


def act(
    hwnd: int,
    action: str,
    target: str = "",
    text: str = "",
    allow_foreground: bool = False,
) -> dict:
    """action: click | type | key | scroll"""
    start = time.perf_counter()
    fg_before = win32.foreground()
    if not win32.title(hwnd):
        return {"ok": False, "reason": "no such window", "detail": f"hwnd {hwnd} is gone"}

    # ---------- tier 1: native child + window message ----------
    if action == "click":
        child = _child(hwnd, target, _BUTTON_CLASSES)
        if child is not None:
            win32.user32.PostMessageW(child["hwnd"], BM_CLICK, 0, 0)
            return _done(hwnd, action, target, "win32:BM_CLICK", fg_before, start)

    if action == "type":
        child = _child(hwnd, target, _TEXT_CLASSES)
        if child is not None:
            buf = ctypes.create_unicode_buffer(text)
            win32.user32.SendMessageW(child["hwnd"], WM_SETTEXT, 0, ctypes.cast(buf, ctypes.c_void_p).value)
            # Read back through UIA: GetWindowTextW is served from another
            # process's message loop and still returns the old text.
            back = _read_text(child["hwnd"])
            if back == text:
                return _done(hwnd, action, target, "win32:WM_SETTEXT", fg_before, start)
            return {
                "ok": False,
                "reason": "control rejected the text",
                "detail": f"WM_SETTEXT left the control holding {back!r}; nothing was typed",
                "foreground_changed": win32.foreground() != fg_before,
            }

    # ---------- tier 2: needs the foreground ----------
    if not allow_foreground:
        why = {
            "click": f"no native control matching {target!r} that accepts a window message",
            "type": f"no native text control matching {target!r}",
            "key": "keyboard focus belongs to the foreground window",
            "scroll": "background scroll is unreliable here (the scroll pattern raised COMError in testing)",
        }.get(action, "no focus-free route")
        return _needs_permission(
            why,
            f"{win32.title(hwnd)!r} can only be reached through UIA or the real cursor, "
            "and both move the foreground to that window.",
        )

    # Tier 2a: routes that work without bringing the window forward.
    # Reading the tree and calling a UIA pattern does not need the foreground on
    # a well-behaved provider, and Chromium's legacy route does not either. Try
    # these first - activating unconditionally is what made every click on an
    # Electron app steal the foreground even when it could have stayed behind.
    elements, _ = tree.read(hwnd, timeout_ms=3000, max_elements=600)
    hit = tree.find(elements, target)
    el = hit["_el"] if hit else None

    if action == "click" and el is not None:
        legacy = tree.pattern(el, "LegacyIAccessiblePattern")
        if legacy is not None:
            try:
                legacy.DoDefaultAction()
                done = _done(hwnd, action, target, "uia:legacy-default", fg_before, start)
                if not done["foreground_changed"]:
                    return done
                # It took the foreground after all; report it honestly below.
                return done
            except Exception:
                pass

    # Tier 2b: everything from here may take the foreground.
    # A background process cannot simply call SetForegroundWindow; Windows
    # refuses silently. win32.activate does the documented workaround and
    # reports whether it worked. If it did not, callers must not type: the
    # keystrokes would land in whatever window is actually in front.
    if not win32.activate(hwnd):
        return {
            "ok": False,
            "reason": "could not bring the window to the foreground",
            "detail": (
                f"Windows refused to activate {win32.title(hwnd)!r}; "
                f"{win32.title(win32.foreground())!r} is still in front. "
                "Nothing was sent, because the input would have gone to the wrong window."
            ),
            "foreground_changed": win32.foreground() != fg_before,
        }

    if el is None:
        elements, _ = tree.read(hwnd, timeout_ms=3000, max_elements=600)
        hit = tree.find(elements, target)
        el = hit["_el"] if hit else None

    if action == "click":
        if el is not None:
            invoke = tree.pattern(el, "InvokePattern")
            if invoke:
                invoke.Invoke()
                return _done(hwnd, action, target, "uia:invoke", fg_before, start)
            toggle = tree.pattern(el, "TogglePattern")
            if toggle:
                toggle.Toggle()
                return _done(hwnd, action, target, "uia:toggle", fg_before, start)
            select = tree.pattern(el, "SelectionItemPattern")
            if select:
                select.Select()
                return _done(hwnd, action, target, "uia:select", fg_before, start)
            # Last resort for a named element: click its own rectangle, not the
            # window centre - the centre may be a different control entirely.
            box = (hit or {}).get("rect")
            if box and box[2] > 0 and box[3] > 0:
                x, y = box[0] + box[2] // 2, box[1] + box[3] // 2
                SetCursorPos(x, y)
                Click(x, y)
                return _done(hwnd, action, target, "cursor:element-rect", fg_before, start)
        x, y = win32.center(hwnd)
        SetCursorPos(x, y)
        Click(x, y)
        return _done(hwnd, action, target, "cursor:window-centre", fg_before, start)

    if action == "type":
        if el is None:
            return {
                "ok": False,
                "reason": "no such control",
                "detail": f"nothing in {win32.title(hwnd)!r} is named {target!r}; nothing was typed",
            }

        # A ValuePattern that refuses SetValue (browser inputs often do) must not
        # fall through to blind keys - they go to whatever holds focus, not to
        # this field. Read back and verify instead.
        vp = tree.pattern(el, "ValuePattern")
        if vp is not None:
            try:
                vp.SetValue(text)
                got = tree.pattern(el, "ValuePattern")
                if got is not None and got.Value == text:
                    return _done(hwnd, action, target, "uia:setvalue", fg_before, start)
            except Exception:
                pass

        # Fall back to real typing: focus the field, clear it, type, verify.
        box = (hit or {}).get("rect")
        if not box or box[2] <= 0 or box[3] <= 0:
            return {
                "ok": False,
                "reason": "control has no clickable area",
                "detail": f"{target!r} reported an empty rectangle; cannot focus it to type",
            }
        x, y = box[0] + box[2] // 2, box[1] + box[3] // 2
        SetCursorPos(x, y)
        Click(x, y)
        time.sleep(0.12)
        SendKeys("{Ctrl}a", interval=0.01, waitTime=0.1)
        SendKeys(text, interval=0.01, waitTime=0.2)

        # Verify by reading the field back where the provider lets us.
        got = tree.pattern(el, "ValuePattern")
        landed = got is not None and got.Value == text
        if got is not None and not landed:
            return {
                "ok": False,
                "reason": "text did not reach the field",
                "detail": f"{target!r} holds {got.Value!r} after typing {text!r}",
                "foreground_changed": win32.foreground() != fg_before,
            }
        return _done(hwnd, action, target, "cursor:click-and-type", fg_before, start)

    if action == "key":
        # Keystrokes need a focused target. SetFocus on the window itself is the
        # only thing that reliably routes them after activation.
        try:
            root = ControlFromHandle(hwnd)
            if root is not None:
                root.SetFocus()
        except Exception:
            pass
        SendKeys(_normalise_keys(text), interval=0.01, waitTime=0.2)
        return _done(hwnd, action, text, "cursor:keys", fg_before, start)

    if action == "scroll":
        el = el if el is not None else ControlFromHandle(hwnd)
        sp = tree.pattern(el, "ScrollPattern") if el is not None else None
        if not sp:
            # Most Win32 controls have no ScrollPattern at all - the wheel is the
            # only way to move them, and that needs the pointer over the target.
            return {
                "ok": False,
                "reason": "not scrollable through UIA",
                "detail": f"{target or 'the window'} exposes no ScrollPattern; only the mouse wheel could move it",
            }
        before = None
        try:
            before = sp.VerticalScrollPercent
        except Exception:
            pass
        try:
            sp.Scroll(0, -3 if text == "up" else 3)
        except Exception as e:
            return {
                "ok": False,
                "reason": "the scroll pattern refused",
                "detail": f"{type(e).__name__}: {e}",
            }
        after = None
        try:
            after = sp.VerticalScrollPercent
        except Exception:
            pass
        result = _done(hwnd, action, target, "uia:scroll", fg_before, start)
        result["scroll_percent"] = [before, after]
        # ScrollPercent is -1 for "not scrollable"; report a no-op as a failure.
        if before is not None and after is not None and before == after:
            return {
                "ok": False,
                "reason": "the view did not move",
                "detail": f"scroll percent stayed at {before}",
                "foreground_changed": result["foreground_changed"],
            }
        return result

    return {"ok": False, "reason": "unknown action", "detail": action}


def _done(hwnd: int, action: str, target: str, route: str, fg_before: int, start: float) -> dict:
    fg_after = win32.foreground()
    return {
        "ok": True,
        "action": action,
        "target": target,
        "route": route,
        "took_ms": round((time.perf_counter() - start) * 1000, 1),
        "foreground_changed": fg_before != fg_after,
        "foreground_before": fg_before,
        "foreground_after": fg_after,
        "window": win32.title(hwnd),
    }
