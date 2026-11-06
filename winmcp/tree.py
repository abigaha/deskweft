"""Look at one window without disturbing the user.

Reading is safe: measured 5 ms - 14 s, foreground never changed. Only pattern
*invocation* steals focus, and that lives in act.py.
"""

from __future__ import annotations

import time

from windows_mcp.uia import ControlFromHandle

DEFAULT_TIMEOUT_MS = 1500
DEFAULT_MAX_ELEMENTS = 200

_PATTERN_NAMES = (
    "InvokePattern",
    "ValuePattern",
    "TogglePattern",
    "SelectionItemPattern",
    "ExpandCollapsePattern",
    "ScrollPattern",
    "RangeValuePattern",
)


def pattern(el, name: str):
    """Fetch one UIA pattern, or None.

    Only control types that implement a pattern expose its getter at all -
    GroupControl has no GetInvokePattern attribute - so a bare attribute access
    crashes on real UIs. Every call site must go through here.
    """
    getter = getattr(el, "Get" + name, None)
    if getter is None:
        return None
    try:
        return getter()
    except Exception:
        return None


def patterns(el) -> list[str]:
    found = []
    for name in _PATTERN_NAMES:
        if pattern(el, name):
            found.append(name.lower())
    return found


def describe(el, nth: int) -> dict:
    """A stable address plus what the element looks like right now."""
    try:
        ct = el.ControlTypeName
    except Exception:
        ct = "?"
    try:
        aid = el.AutomationId or ""
    except Exception:
        aid = ""
    try:
        name = (el.Name or "").strip()
    except Exception:
        name = ""
    try:
        rect = el.BoundingRectangle
        box = [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top]
    except Exception:
        box = None
    return {
        "control_type": ct,
        "automation_id": aid,
        "name": name,
        "nth": nth,
        "patterns": patterns(el),
        "rect": box,
        "_el": el,
    }


def read(hwnd: int, timeout_ms: int = DEFAULT_TIMEOUT_MS, max_elements: int = DEFAULT_MAX_ELEMENTS):
    """Walk one window's tree. Returns (elements, timed_out).

    Each element carries a reference string for act(). References are resolved
    against the live tree on every call, so a stale reference fails loudly
    instead of clicking whatever now sits at the old coordinates.
    """
    deadline = time.perf_counter() + max(0, timeout_ms) / 1000

    # ControlFromHandle raises COMError for a handle that is not a window, and a
    # COMError escaping here reaches the caller as a server error instead of a
    # usable answer. Treat every such handle as "nothing to read".
    try:
        root = ControlFromHandle(hwnd)
    except Exception:
        return [], False
    if root is None:
        return [], False

    elements: list[dict] = []
    counts: dict[tuple, int] = {}
    timed_out = False

    def walk(el, depth: int) -> None:
        nonlocal timed_out
        if timed_out or len(elements) >= max_elements:
            return
        try:
            kids = el.GetChildren()
        except Exception:
            return
        for kid in kids:
            if time.perf_counter() > deadline:
                timed_out = True
                return
            if len(elements) >= max_elements:
                return
            try:
                if kid.IsOffscreen:
                    continue
            except Exception:
                continue
            info = describe(kid, 0)
            # Keep anything named or actionable; drop anonymous containers.
            if not info["name"] and not info["patterns"]:
                walk(kid, depth)
                continue
            key = (info["control_type"], info["automation_id"], info["name"])
            info["nth"] = counts.get(key, 0)
            counts[key] = info["nth"] + 1
            info["depth"] = depth
            elements.append(info)
            walk(kid, depth + 1)

    try:
        walk(root, 0)
    except Exception:
        pass
    return elements, timed_out


def find(elements: list[dict], ref: str) -> dict | None:
    """Locate by name/automation id, exact first then case-insensitive substring."""
    if not ref:
        return None
    by_id = [e for e in elements if e["automation_id"] == ref]
    if by_id:
        return by_id[0]
    exact = [e for e in elements if e["name"] == ref]
    if exact:
        return exact[0]
    low = ref.casefold()
    loose = [e for e in elements if e["name"] and low in e["name"].casefold()]
    if loose:
        return loose[0]
    return None
