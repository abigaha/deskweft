"""Drive a window: refuse uncertain targets, then say what actually happened.

Two tiers, and the tier is decided by evidence, not by hope:

  tier 1  Win32 messages to a native child HWND. Measured: 0.0 ms, foreground
          unchanged. Always allowed; the result is read back where a readback
          exists, and "the message was posted" is reported as queued, never as
          an effect.
  tier 2  UIA pattern calls and real input. Measured: UIA InvokePattern moved the
          foreground (504-518 ms per call) on this machine. Never allowed
          without allow_foreground=True - the caller must have permission first.

A target that is missing, ambiguous or read from an incomplete tree is refused
before anything is sent. There is no "click the window centre" fallback: that
turns a failed lookup into an unwanted click somewhere else.
"""

from __future__ import annotations

import inspect
import time

from windows_mcp.uia import Click, ControlFromHandle, SendKeys, SetCursorPos
from windows_mcp.uia.enums import ScrollAmount
from windows_mcp.uia.patterns import PatternConstructors, TextRange

from windows_mcp.uia import Control

from . import launch, tree, win32

BM_CLICK = 0x00F5
WM_SETTEXT = 0x000C
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202

MAX_TEXT = 6000
MAX_ITEMS = 100
MAX_DEPTH = 4

# Only classes that are really pressable accept BM_CLICK. Anything else - a
# render host, a D3D window, a composition surface - answers PostMessage and
# does nothing, which is worse than refusing.
_BUTTON_CLASSES = ("Button", "msctls_", "ToolbarWindow32", "SSTabCtlWndClass", "SHELLDLL")
# Class tokens that can hold text a message can write. WinForms names its
# classes WindowsForms10.Edit..., so match anywhere in the class string.
_TEXT_CLASSES = ("Edit", "RICHEDIT", "Scintilla", "ComboBox")

# Members that only read. Matched by full member path, case-sensitively: a
# Get prefix is not evidence of safety, and a provider's Getter can still move
# the foreground - which is why a measured counterexample belongs in memory.
_READ_ONLY_MEMBERS = {
    "ValuePattern": {"Value", "IsReadOnly"},
    "RangeValuePattern": {"Value", "IsReadOnly", "Minimum", "Maximum",
                          "SmallChange", "LargeChange"},
    "SelectionPattern": {"GetSelection", "CanSelectMultiple", "IsSelectionRequired"},
    "SelectionItemPattern": {"IsSelected"},
    "TextPattern": {"DocumentRange.GetText", "GetSelection", "GetVisibleRanges",
                    "SupportedTextSelection"},
    "ScrollPattern": {"HorizontallyScrollable", "VerticallyScrollable",
                      "HorizontalScrollPercent", "VerticalScrollPercent",
                      "HorizontalViewSize", "VerticalViewSize"},
}

# Wrapper methods that act on the UI. Listed, never inferred from a name prefix.
_ACTION_METHODS = {
    "Invoke", "Toggle", "Select", "Expand", "Collapse", "SetValue", "Scroll",
    "DoDefaultAction", "Move", "Resize", "Close",
}

_TRUSTED = tuple(PatternConstructors.values()) + (Control, TextRange)
_RESERVED_FIELDS = {"_element", "element", "pattern", "textRange", "Element", "Pattern"}


class Unsupported(Exception):
    """A returned object has no projection yet."""


class _Budget:
    """Transport bounds for one projected result. Not a limit on stored knowledge."""

    def __init__(self) -> None:
        self.chars = MAX_TEXT
        self.items = MAX_ITEMS
        self.truncated = False


def _needs_permission(reason: str, detail: str) -> dict:
    return {
        "ok": False,
        "needs_permission": True,
        "reason": reason,
        "detail": detail,
        "execution_state": "not_started",
        "effect_verified": False,
        "retry_safe": True,
        "hint": "Show this to the user. Retry with allow_foreground=true only after they agree.",
    }


def _fail(reason: str, detail: str, before: int, *, state: str = "not_started",
          **extra) -> dict:
    after = win32.foreground()
    out = {"ok": False, "reason": reason, "detail": detail,
           "execution_state": state, "effect_verified": False,
           "retry_safe": state == "not_started",
           "foreground_before": before, "foreground_after": after,
           "foreground_changed": before != after}
    out.update(extra)
    return out


def _child(hwnd: int, target: str, classes: tuple[str, ...]) -> dict:
    """A native child of an allowed class, only when the match is unique.

    Layers keep the old priority - exact text, text substring, class substring -
    but each layer must yield exactly one candidate. Taking the first of several
    is how a click lands on the wrong button.
    """
    kids = [k for k in win32.children(hwnd)
            if any(c.casefold() in k["class"].casefold() for c in classes)]
    if not target:
        if len(kids) == 1:
            return {"ok": True, "child": kids[0]}
        # No name and no unique native control: a click on "whatever is here"
        # is exactly the guess this tool refuses to make.
        return {"ok": False, "reason": "target required",
                "detail": (f"{len(kids)} native controls and no target to choose "
                           "between them" if kids else "no native control of an allowed class")}
    layers = [
        ("exact text", lambda k: k["text"] == target),
        ("text substring", lambda k: bool(k["text"]) and target.casefold() in k["text"].casefold()),
    ]
    low = target.casefold()
    layers.append(("class", lambda k: low in k["class"].casefold()))
    for label, predicate in layers:
        matches = [k for k in kids if predicate(k)]
        if len(matches) == 1:
            return {"ok": True, "child": matches[0]}
        if len(matches) > 1:
            return {"ok": False, "reason": "ambiguous target",
                    "detail": f"{len(matches)} native controls match {target!r} by {label}"}
    return {"ok": False, "reason": "no such control",
            "detail": f"no native control of an allowed class matches {target!r}"}


def _read_text(child_hwnd: int) -> str | None:
    """Current text of a control, read through UIA (works across processes)."""
    try:
        el = ControlFromHandle(child_hwnd)
        vp = tree.pattern(el, "ValuePattern") if el is not None else None
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


def _target(hwnd: int, target: str, before: int) -> dict:
    """Resolve a target through the detailed tree, or return the refusal."""
    detailed = tree.read_detailed(hwnd, timeout_ms=3000, max_elements=600)
    found = tree.resolve(detailed, target)
    if not found["ok"]:
        return found
    return {"ok": True, "hit": found["element"], "detailed": detailed}


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
        return _fail("no such window", f"hwnd {hwnd} is gone", fg_before)

    # ---------- tier 1: native child + window message ----------
    if action == "click":
        found = _child(hwnd, target, _BUTTON_CLASSES)
        if found["ok"]:
            child = found["child"]
            posted = win32.user32.PostMessageW(child["hwnd"], BM_CLICK, 0, 0)
            if not posted:
                return _fail("message delivery failed",
                             f"PostMessageW(BM_CLICK) to hwnd {child['hwnd']} returned 0",
                             fg_before)
            return _done(hwnd, action, target, "win32:BM_CLICK", fg_before, start,
                         delivery="queued")
        if found["reason"] == "ambiguous target":
            return _fail(found["reason"], found["detail"], fg_before)

    if action == "type":
        found = _child(hwnd, target, _TEXT_CLASSES)
        if found["ok"]:
            child = found["child"]
            # The internal managed write, not the public wrapper: the wrapper's
            # setter permission gate must not change native type's behaviour.
            written = win32._write_text(child["hwnd"], text, _units(text), 1000, 4096,
                                        win32.foreground())
            if not written["ok"]:
                return _fail(written["reason"], written.get("detail", ""), fg_before,
                             state=written.get("execution_state", "not_started"),
                             effect_verified=False)
            return _done(hwnd, action, target, "win32:WM_SETTEXT", fg_before, start,
                         delivery="returned",
                         effect_verified=written.get("effect_verified", False),
                         verification_reason=written.get("verification_reason"))
        if found["reason"] == "ambiguous target":
            return _fail(found["reason"], found["detail"], fg_before)

    # ---------- tier 2: needs the foreground ----------
    if not allow_foreground:
        if action == "click" and not target:
            # An empty target with no unique native match is not a request to
            # click "something here"; say what is missing instead.
            return _fail("target required",
                         "click needs the name of one control; nothing was clicked",
                         fg_before)
        why = {
            "click": f"no single native control matching {target!r} that accepts a window message",
            "type": f"no single native text control matching {target!r}",
            "key": "keyboard focus belongs to the foreground window",
            "scroll": "background scroll is unreliable here (the scroll pattern raised COMError in testing)",
        }.get(action, "no focus-free route")
        return _needs_permission(
            why,
            f"{win32.title(hwnd)!r} can only be reached through UIA or the real cursor, "
            "and both may move the foreground to that window.",
        )

    if action == "key":
        return _keys(hwnd, text, fg_before, start)

    # Resolve before activating: a tree that cannot be read completely must not
    # be followed by a guess at the real cursor.
    if action == "scroll" and not target:
        el = ControlFromHandle(hwnd)
        return _scroll(hwnd, el, "", text, fg_before, start)

    found = _target(hwnd, target, fg_before)
    if not found["ok"]:
        return _fail(found["reason"], found["detail"], fg_before)
    hit = found["hit"]
    el = hit["_el"]

    if action == "click":
        return _click_uia(hwnd, hit, el, target, fg_before, start)
    if action == "type":
        return _type_uia(hwnd, hit, el, target, text, fg_before, start)
    if action == "scroll":
        return _scroll(hwnd, el, target, text, fg_before, start)
    return _fail("unknown action", action, fg_before)


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _click_uia(hwnd: int, hit: dict, el, target: str, fg_before: int, start: float) -> dict:
    """Legacy first (measured not to take the foreground), then the other routes.

    Once a route has been called, its real outcome is reported: a False return,
    an exception or an unreadable value stops the chain instead of quietly
    trying another side-effecting route.
    """
    for name, call, label in (
        ("LegacyIAccessiblePattern", "DoDefaultAction", "uia:legacy-default"),
        ("InvokePattern", "Invoke", "uia:invoke"),
        ("TogglePattern", "Toggle", "uia:toggle"),
        ("SelectionItemPattern", "Select", "uia:select"),
    ):
        result = tree.pattern_detailed(el, name)
        if not result["ok"]:
            if result["reason"] == "provider error":
                # The getter itself failed. That is evidence about this provider,
                # not proof the pattern is absent, and quietly trying another
                # side-effecting route would perform a call nobody authorised.
                return _fail("provider error", result["detail"], fg_before)
            continue  # absent or unwrapped here: the next documented route may exist
        member = getattr(result["value"], call, None)
        if not callable(member):
            continue
        try:
            returned = member()
        except Exception as error:
            return _fail("provider error",
                         f"{result['canonical']}.{call}: {type(error).__name__}: {error}",
                         fg_before, state="unknown")
        if returned is False:
            return _done(hwnd, "click", target, label, fg_before, start,
                         ok=False, reason="provider reported false",
                         effect_verified=False)
        return _done(hwnd, "click", target, label, fg_before, start)

    box = hit.get("rect")
    if box and box[2] > 0 and box[3] > 0:
        if not win32.activate(hwnd):
            return _fail("could not bring the window to the foreground",
                         f"Windows refused to activate {win32.title(hwnd)!r}; nothing was clicked",
                         fg_before)
        x, y = box[0] + box[2] // 2, box[1] + box[3] // 2
        SetCursorPos(x, y)
        Click(x, y)
        return _done(hwnd, "click", target, "cursor:element-rect", fg_before, start)
    return _fail("control has no clickable area",
                 f"{target!r} exposes no action pattern and reported an empty rectangle",
                 fg_before)


def _type_uia(hwnd: int, hit: dict, el, target: str, text: str,
              fg_before: int, start: float) -> dict:
    """ValuePattern first; real typing only when the pattern is absent.

    A pattern that exists but cannot be read is "unverified", not "nothing
    written", and a read-back that differs is a mismatch - never a claim that
    the text landed.
    """
    result = tree.pattern_detailed(el, "ValuePattern")
    if result["ok"]:
        pattern = result["value"]
        try:
            pattern.SetValue(text)
        except Exception as error:
            return _fail("provider error",
                         f"ValuePattern.SetValue: {type(error).__name__}: {error}",
                         fg_before, state="unknown")
        try:
            landed = pattern.Value
        except Exception as error:
            return _done(hwnd, "type", target, "uia:setvalue", fg_before, start,
                         ok=False, reason="readback unavailable",
                         effect_verified=False,
                         verification_reason=f"{type(error).__name__}: {error}")
        if landed == text:
            return _done(hwnd, "type", target, "uia:setvalue", fg_before, start,
                         effect_verified=True)
        return _fail("text readback mismatch",
                     f"{target!r} holds {str(landed)[:80]!r} after writing {text!r}",
                     fg_before, state="completed")

    if result["reason"] in ("unknown pattern", "pattern not wrapped"):
        return _fail(result["reason"], result["detail"], fg_before)
    if not result.get("cause_unknown") and result["reason"] == "provider error":
        return _fail(result["reason"], result["detail"], fg_before)

    # The pattern is absent or unreadable: type for real, then read back.
    box = hit.get("rect")
    if not box or box[2] <= 0 or box[3] <= 0:
        return _fail("control has no clickable area",
                     f"{target!r} reported an empty rectangle; cannot focus it to type",
                     fg_before)
    if not win32.activate(hwnd):
        return _fail("could not bring the window to the foreground",
                     f"Windows refused to activate {win32.title(hwnd)!r}; nothing was typed",
                     fg_before)
    x, y = box[0] + box[2] // 2, box[1] + box[3] // 2
    SetCursorPos(x, y)
    Click(x, y)
    time.sleep(0.12)
    SendKeys("{Ctrl}a", interval=0.01, waitTime=0.1)
    SendKeys(text, interval=0.01, waitTime=0.2)

    again = tree.pattern_detailed(el, "ValuePattern")
    if not again["ok"]:
        return _done(hwnd, "type", target, "cursor:click-and-type", fg_before, start,
                     effect_verified=False, verification_reason="readback unavailable")
    if again["value"].Value != text:
        return _fail("text readback mismatch",
                     f"{target!r} holds {str(again['value'].Value)[:80]!r} after typing",
                     fg_before, state="completed")
    return _done(hwnd, "type", target, "cursor:click-and-type", fg_before, start,
                 effect_verified=True)


def _scroll(hwnd: int, el, target: str, direction: str, fg_before: int,
            start: float) -> dict:
    if direction not in ("up", "down"):
        return _fail("invalid arguments", "direction must be 'up' or 'down'", fg_before)
    result = tree.pattern_detailed(el, "ScrollPattern") if el is not None else \
        {"ok": False, "reason": "no such control", "detail": "target not found"}
    if not result["ok"]:
        if result["reason"] in ("no such control", "target required", "tree incomplete",
                                "ambiguous target"):
            return _fail(result["reason"], result.get("detail", ""), fg_before)
        return _fail("not scrollable through UIA",
                     f"{target or 'the window'} exposes no ScrollPattern; only the mouse "
                     "wheel could move it", fg_before)
    pattern = result["value"]
    before = _percent(pattern)
    vertical = (ScrollAmount.LargeDecrement if direction == "up"
                else ScrollAmount.LargeIncrement)
    try:
        reported = pattern.Scroll(ScrollAmount.NoAmount, vertical)
    except Exception as error:
        return _fail("the scroll pattern refused",
                     f"{type(error).__name__}: {error}", fg_before, state="unknown")
    after = _percent(pattern)
    done = _done(hwnd, "scroll", target, "uia:scroll", fg_before, start,
                 effect_verified=None)
    done["scroll_percent"] = [before, after]
    if reported is False:
        return _fail("provider reported false", "ScrollPattern.Scroll returned False",
                     fg_before, state="completed", scroll_percent=[before, after])
    if before is not None and after is not None and before == after:
        return _fail("the view did not move", f"scroll percent stayed at {before}",
                     fg_before, state="completed", scroll_percent=[before, after])
    done["effect_verified"] = before is not None and after is not None and before != after
    return done


def _percent(pattern) -> float | None:
    try:
        return pattern.VerticalScrollPercent
    except Exception:
        return None


def _keys(hwnd: int, keys: str, fg_before: int, start: float) -> dict:
    """Real keystrokes only when the target really holds the focus."""
    if win32.foreground() != hwnd:
        return _fail("target not focused",
                     f"{win32.title(hwnd)!r} is not the foreground window; keystrokes "
                     "would land in another application", fg_before)
    if not launch.is_shown(hwnd):
        return _fail("target not visible",
                     f"{win32.title(hwnd)!r} is hidden or minimised", fg_before)
    try:
        root = ControlFromHandle(hwnd)
        if root is not None:
            root.SetFocus()
    except Exception as error:
        # Focus could not be placed deliberately; the keystrokes would go to
        # whatever really holds it, so report that instead of sending them.
        return _fail("target not focused",
                     f"SetFocus on {win32.title(hwnd)!r} failed: "
                     f"{type(error).__name__}: {error}; nothing was sent", fg_before)
    SendKeys(_normalise_keys(keys), interval=0.01, waitTime=0.2)
    return _done(hwnd, "key", keys, "cursor:keys", fg_before, start)


def _done(hwnd: int, action: str, target: str, route: str, fg_before: int,
          start: float, *, ok: bool = True, effect_verified: bool = False,
          delivery: str = "returned", **extra) -> dict:
    fg_after = win32.foreground()
    out = {
        "ok": ok,
        "action": action,
        "target": target,
        "route": route,
        "took_ms": round((time.perf_counter() - start) * 1000, 1),
        "call_completed": True,
        "delivery": delivery,
        "effect_verified": effect_verified,
        "execution_state": "completed",
        "foreground_changed": fg_before != fg_after,
        "foreground_before": fg_before,
        "foreground_after": fg_after,
        "window": win32.title(hwnd),
    }
    for key, value in extra.items():
        if value is not None:
            out[key] = value
    return out


# ---------- invoke_pattern ----------


def _valid_hwnd(hwnd) -> bool:
    return (isinstance(hwnd, int) and not isinstance(hwnd, bool)
            and 0 < hwnd < 0x10000000 and hwnd != 0xFFFF)


def _identifiers(method: str) -> list[str]:
    """A public member path, or Invalid. No expression, no eval, no private names."""
    parts = method.split(".")
    for part in parts:
        if not part or not (part[0].isalpha() or part[0] == "_"):
            raise ValueError(f"{method!r} is not a member path")
        if part.startswith("_"):
            raise ValueError("private members are not reachable")
        if not part.replace("_", "").isalnum():
            raise ValueError(f"{part!r} is not an identifier")
    return parts


def _argument_error(args) -> str | None:
    if args is None:
        return None
    if not isinstance(args, list):
        return "args must be a list"
    for value in args:
        if isinstance(value, bool) or isinstance(value, int) or isinstance(value, str):
            continue
        if isinstance(value, float) and value == value and abs(value) != float("inf"):
            continue
        return f"{value!r} is not a finite JSON scalar"
    return None


def _member(el, part: str):
    """A wrapper member reachable only through a declared public descriptor."""
    try:
        descriptor = inspect.getattr_static(type(el), part)
    except AttributeError:
        descriptor = None
    if descriptor is None:
        value = getattr(el, part, None)
        return value, True
    if isinstance(descriptor, property):
        return getattr(el, part), True
    return None, False


def _walk(value, path: str, budget: _Budget):
    """Follow a public property path; intermediate members must be wrappers."""
    for part in path.split(".")[:-1]:
        if not isinstance(value, _TRUSTED):
            raise Unsupported(f"{part} is not a supported wrapper")
        next_value, is_property = _member(value, part)
        if is_property is False:
            raise Unsupported(f"{part} is a method, not a property")
        if not isinstance(next_value, _TRUSTED):
            raise Unsupported(f"{part} leads to {type(next_value).__name__}, which this "
                              "service cannot project")
        value = next_value
    return value


def _plain_result(value, budget: _Budget, depth: int = 0):
    """Convert a UIA result into plain data, bounded and honest about it.

    Raw COM objects never leave this function. `Unsupported` means "no
    projection for this type yet" - the caller reports it, it is not a success.
    """
    if depth > MAX_DEPTH:
        budget.truncated = True
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or abs(value) == float("inf"):
            raise Unsupported("non-finite float")
        return value
    if isinstance(value, str):
        if len(value) > budget.chars:
            budget.truncated = True
            value = value[:max(0, budget.chars)]
        budget.chars -= len(value)
        return value
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if budget.items <= 0 or budget.chars <= 0:
                budget.truncated = True
                break
            budget.items -= 1
            out.append(_plain_result(item, budget, depth + 1))
        return out
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise Unsupported("mapping keys must be strings")
            if budget.items <= 0 or budget.chars <= 0:
                budget.truncated = True
                break
            budget.items -= 1
            out[key] = _plain_result(item, budget, depth + 1)
        return out
    if isinstance(value, TextRange):
        return _project_range(value, budget)
    if isinstance(value, Control):
        described = tree.describe(value, 0)
        described.pop("_el", None)
        return described
    raise Unsupported(f"{type(value).__name__} has no projection yet")


def _project_range(value: TextRange, budget: _Budget) -> dict:
    """Read a text range in this thread, never returning the range itself."""
    cap = max(1, min(MAX_TEXT, budget.chars))
    try:
        text = value.GetText(cap + 1) or ""
    except Exception as error:
        raise Unsupported(f"TextRange.GetText: {type(error).__name__}: {error}") from None
    api_capped = len(text.encode("utf-16-le")) // 2 >= cap
    if len(text) > cap:
        text = text[:cap]
    budget.chars -= len(text)
    if api_capped:
        budget.truncated = True
    return {"type": "text_range", "text": text, "possibly_truncated": api_capped}


def _pattern_id_hint(pattern: str) -> dict:
    known = tree._KNOWN.get(pattern.casefold())
    return {"pattern_id": known[1]} if known else {}


def invoke_pattern(hwnd: int, pattern: str, target: str,
                   method: str, args: list | None = None,
                   allow_foreground: bool = False,
                   timeout_ms: int = 8000) -> dict:
    """Read or call one public UIA pattern member on a uniquely named control.

    `method` is a public member path such as "Value" or
    "DocumentRange.GetText"; the last part is called if it is a method and read
    if it is a property. Only members on the read-only table run without
    allow_foreground - a Get prefix is not proof of safety.

    target="" means the window's root element. Any other target is resolved in
    the same thread against a complete tree, exact AutomationId then exact name;
    a miss, a tie or an incomplete tree refuses before the provider is touched.
    """
    before = win32.foreground()
    started = time.perf_counter()
    if not _valid_hwnd(hwnd):
        return _fail("invalid hwnd", repr(hwnd), before)
    if not isinstance(pattern, str) or not pattern.strip():
        return _fail("invalid arguments", "pattern must be a non-empty name", before)
    if not isinstance(method, str) or not method.strip():
        return _fail("invalid arguments", "method must be a non-empty member path", before)
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) \
            or not 1 <= timeout_ms <= 30000:
        return _fail("invalid arguments", "timeout_ms must be 1..30000", before)
    if not isinstance(allow_foreground, bool) or not isinstance(target, str):
        return _fail("invalid arguments", "target must be a string and allow_foreground a bool",
                     before)
    bad_args = _argument_error(args)
    if bad_args:
        return _fail("invalid arguments", bad_args, before)
    args = [] if args is None else args
    try:
        parts = _identifiers(method)
    except ValueError as error:
        return _fail("invalid arguments", str(error), before)
    if any(part in _RESERVED_FIELDS for part in parts):
        return _fail("invalid arguments",
                     "raw COM fields cannot be navigated; use a pattern member", before)

    canonical = tree._KNOWN.get(pattern.casefold())
    read_only = canonical is not None and method in _READ_ONLY_MEMBERS.get(
        canonical[0], set())
    is_action = parts[-1] in _ACTION_METHODS

    # Arguments are the caller's own mistake; report that before asking for
    # permission to do something it could never legally do anyway.
    if canonical is not None and canonical[0] == "TextPattern" \
            and method == "DocumentRange.GetText":
        cap = args[0] if args else None
        if cap is None or isinstance(cap, bool) or not isinstance(cap, int) \
                or not 1 <= cap <= MAX_TEXT + 1:
            return _fail("invalid arguments",
                         "DocumentRange.GetText needs maxLength in 1..6001", before)
    elif read_only and args and len(parts) == 1:
        return _fail("invalid arguments", f"{method} is a property and takes no arguments",
                     before)

    if not read_only and not allow_foreground:
        result = _needs_permission(
            f"{pattern}.{method} may change the window or its data",
            "Pass allow_foreground=true only after the user agrees to this specific action.",
        )
        result.update({"foreground_before": before, "foreground_after": win32.foreground(),
                       "foreground_changed": False})
        return result

    # Resolve the target in this thread, before anything is called.
    if target == "":
        try:
            el = ControlFromHandle(hwnd)
        except Exception as error:
            return _fail("provider error", f"ControlFromHandle: {error}", before,
                         state="unknown")
        if el is None:
            return _fail("no such control", f"hwnd {hwnd} has no UIA root", before)
    else:
        detailed = tree.read_detailed(hwnd, timeout_ms=min(3000, timeout_ms),
                                      max_elements=600)
        found = tree.resolve(detailed, target, exact_only=True)
        if not found["ok"]:
            return _fail(found["reason"], found["detail"], before)
        el = found["element"]["_el"]

    result = tree.pattern_detailed(el, pattern)
    if not result["ok"]:
        out = _fail(result["reason"], result.get("detail", ""), before,
                    pattern_id=result.get("pattern_id"))
        if result.get("cause_unknown"):
            out["cause_unknown"] = True
        out.update(_pattern_id_hint(pattern))
        return out
    value = result["value"]

    try:
        holder = _walk(value, method, _Budget())
    except Unsupported as error:
        return _fail("member unavailable", str(error), before, state="unknown")

    last = parts[-1]
    try:
        descriptor = inspect.getattr_static(type(holder), last)
        declared = isinstance(descriptor, property)
    except AttributeError:
        declared = not callable(getattr(holder, last, None))
    if declared and args:
        return _fail("invalid arguments", f"{last} is a property and takes no arguments",
                     before)

    try:
        if declared:
            returned = getattr(holder, last)
        else:
            member = getattr(holder, last, None)
            if not callable(member):
                return _fail("member unavailable", f"{method} is not callable here", before)
            returned = member(*args)
    except Exception as error:
        return _fail("provider error",
                     f"{pattern}.{method}: {type(error).__name__}: {error}", before,
                     state="unknown")

    if is_action and returned is False:
        return _fail("provider reported false", f"{pattern}.{method} returned False",
                     before, state="completed", call_completed=True)

    budget = _Budget()
    try:
        projected = _plain_result(returned, budget)
    except Unsupported as error:
        return _fail("result unsupported", str(error), before, state="completed",
                     call_completed=True, result_type=type(returned).__name__)

    # An explicit GetText answers with a bare string; report it as a bounded
    # read with its own truncation flag, which is not the transport flag.
    possibly_truncated = False
    if canonical is not None and canonical[0] == "TextPattern" \
            and method == "DocumentRange.GetText" and isinstance(projected, str):
        wanted = args[0]
        possibly_truncated = len(projected.encode("utf-16-le")) // 2 >= wanted
        projected = {"type": "text", "text": projected,
                     "possibly_truncated": possibly_truncated}

    out = _done(hwnd, "invoke_pattern", target, f"uia:{result['canonical']}", before,
                started)
    out["pattern"] = result["canonical"]
    out["pattern_id"] = result["pattern_id"]
    out["method"] = method
    out["call_completed"] = True
    out["result"] = projected
    out["result_truncated"] = budget.truncated
    out["effect_verified"] = False
    if possibly_truncated:
        out["possibly_truncated"] = True
    return out
