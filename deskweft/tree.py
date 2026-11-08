"""Look at one window without disturbing the user.

Reading is safe: measured 5 ms - 14 s, foreground never changed. Only pattern
*invocation* steals focus, and that lives in act.py.

`read_detailed` is the diagnostic entry: it says why a tree is short instead of
letting an empty list look like "this application has no accessibility". The
time budget only stops the Python walk - it cannot interrupt a blocked provider
call, which is why the worker process exists.
"""

from __future__ import annotations

import time

from windows_mcp.uia import ControlFromHandle
from windows_mcp.uia.enums import PatternIdNames
from windows_mcp.uia.patterns import PatternConstructors, TextRange

DEFAULT_TIMEOUT_MS = 1500
DEFAULT_MAX_ELEMENTS = 200
MAX_WARNINGS = 50

_PATTERN_NAMES = (
    "InvokePattern",
    "ValuePattern",
    "TogglePattern",
    "SelectionItemPattern",
    "ExpandCollapsePattern",
    "ScrollPattern",
    "RangeValuePattern",
)

# GetPattern takes a numeric id, not a name. Only ids with a wrapper in the
# installed dependency can be returned at all, so the map is built from the
# dependency's own constructor table rather than a guess.
_KNOWN = {name.casefold(): (name, int(pid)) for pid, name in PatternIdNames.items()}
_SUPPORTED = {key: value for key, value in _KNOWN.items()
              if value[1] in PatternConstructors}


def pattern_detailed(el, name: str) -> dict:
    """One pattern, or a reason it is not here.

    A wrapper returning None proves nothing: the installed GetPattern swallows
    COMError, so "the provider refused" and "the dependency failed" arrive the
    same way. That is `cause_unknown`, not `pattern not exposed`.
    """
    known = _KNOWN.get(name.casefold())
    if known is None:
        return {"ok": False, "reason": "unknown pattern", "detail": name}
    canonical, pid = known
    if name.casefold() not in _SUPPORTED:
        return {"ok": False, "reason": "pattern not wrapped",
                "detail": canonical, "pattern_id": pid}
    try:
        getter = getattr(el, "Get" + canonical, None)
        value = getter() if callable(getter) else el.GetPattern(pid)
    except Exception as error:
        return {"ok": False, "reason": "provider error",
                "detail": f"{type(error).__name__}: {error}", "pattern_id": pid}
    if value is None:
        return {"ok": False, "reason": "pattern unavailable",
                "detail": "wrapper returned None; exposure or failure is unknown",
                "pattern_id": pid, "cause_unknown": True}
    return {"ok": True, "value": value, "canonical": canonical, "pattern_id": pid}


def pattern(el, name: str):
    """Fetch one UIA pattern, or None. Kept for existing callers."""
    result = pattern_detailed(el, name)
    return result["value"] if result["ok"] else None


def patterns(el) -> list[str]:
    """The seven common patterns this node exposes. A summary, not an inventory."""
    return [name.lower() for name in _PATTERN_NAMES if pattern(el, name)]


def _read(el, attribute, default, stage: str, diagnostics: dict):
    """Read one optional attribute, recording a failure instead of trusting it."""
    try:
        return getattr(el, attribute)
    except Exception as error:
        # AutomationId/Name feed addressing, so failing to read one breaks the
        # completeness claim; an optional pattern or rect does not.
        _warn_into(diagnostics, stage, error,
                   typed=stage in ("name", "automation_id"))
        return default


def _warn_into(diagnostics: dict, stage: str, error: Exception, el=None, depth=None,
               typed: bool = False) -> None:
    warnings = diagnostics["warnings"]
    if typed:
        # AutomationId/Name feed addressing: failing to read one breaks the
        # claim that the tree was read completely, unlike an optional pattern.
        diagnostics["identity_broken"] = True
    if len(warnings) < MAX_WARNINGS:
        warnings.append({
            "stage": stage, "error_type": type(error).__name__,
            "message": f"{type(error).__name__}: {error}",
            "control_type": diagnostics.get("control_type", ""),
            "automation_id": diagnostics.get("automation_id", ""),
            "name": diagnostics.get("name", ""), "depth": depth,
        })
    else:
        diagnostics["warnings_truncated"] = True


def _describe(el, nth: int, diagnostics: dict, depth: int | None = None) -> dict:
    """A stable address plus what the element looks like right now.

    `_el` stays for act(); every other value is plain data that can cross a
    process boundary.
    """
    control_type = _read(el, "ControlTypeName", "?", "control_type", diagnostics)
    diagnostics["control_type"] = control_type
    automation_id = _read(el, "AutomationId", "", "automation_id", diagnostics) or ""
    diagnostics["automation_id"] = automation_id
    name = (_read(el, "Name", "", "name", diagnostics) or "").strip()
    diagnostics["name"] = name
    try:
        rect = el.BoundingRectangle
        box = [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top]
    except Exception as error:
        _warn_into(diagnostics, "rect", error, depth=depth)
        box = None
    native = None
    try:
        native = int(el.NativeWindowHandle or 0) or None
    except Exception as error:
        _warn_into(diagnostics, "native_hwnd", error, depth=depth)
    return {
        "control_type": control_type,
        "automation_id": automation_id,
        "name": name,
        "nth": nth,
        "patterns": patterns(el),
        "rect": box,
        "native_hwnd": native,
        "_el": el,
    }


def describe(el, nth: int) -> dict:
    """Public wrapper kept at its old signature."""
    diagnostics = {"warnings": [], "warnings_truncated": False, "identity_complete": True}
    diagnostics["warn"] = lambda stage, error, typed=False: _warn_into(
        diagnostics, stage, error, typed=typed)
    return _describe(el, nth, diagnostics)


def read_detailed(hwnd: int, timeout_ms: int = DEFAULT_TIMEOUT_MS,
                  max_elements: int = DEFAULT_MAX_ELEMENTS) -> dict:
    """Walk one window's tree and report what was and was not readable."""
    result = {"elements": [], "timed_out": False, "limit_reached": False,
              "identity_complete": True,
              "tree_diagnostics": {"root_status": "ok", "filtered_anonymous": 0,
                                   "filtered_offscreen": 0, "warnings": [],
                                   "warnings_truncated": False}}
    diagnostics = result["tree_diagnostics"]
    diagnostics["warn"] = lambda stage, error, typed=False, **kw: _warn_into(
        diagnostics, stage, error, typed=typed, **kw)

    try:
        root = ControlFromHandle(hwnd)
    except Exception as error:
        diagnostics["root_status"] = "provider_error"
        result["identity_complete"] = False
        _warn_into(diagnostics, "root", error)
        return _strip(result)
    if root is None:
        # Absent root: the reason may be a timeout, an empty frame or a real
        # refusal. It is not evidence that the application lacks UIA.
        diagnostics["root_status"] = "absent"
        return _strip(result)

    deadline = time.perf_counter() + max(0, timeout_ms) / 1000
    elements: list[dict] = []
    counts: dict[tuple, int] = {}

    def walk(el, depth: int) -> None:
        if result["timed_out"] or result["limit_reached"]:
            return
        try:
            children = el.GetChildren()
        except Exception as error:
            result["identity_complete"] = False
            _warn_into(diagnostics, "children", error, depth=depth)
            return
        for child in children:
            if time.perf_counter() > deadline:
                result["timed_out"] = True
                return
            if len(elements) >= max_elements:
                result["limit_reached"] = True
                return
            try:
                offscreen = child.IsOffscreen
            except Exception as error:
                result["identity_complete"] = False
                _warn_into(diagnostics, "offscreen", error, depth=depth)
                continue
            if offscreen:
                diagnostics["filtered_offscreen"] += 1
                continue
            info = _describe(child, 0, diagnostics, depth)
            # An unnamed node can still match an id/type/handle selector.
            key = (info["control_type"], info["automation_id"], info["name"])
            info["nth"] = counts.get(key, 0)
            counts[key] = info["nth"] + 1
            info["depth"] = depth
            elements.append(info)
            walk(child, depth + 1)

    try:
        walk(root, 0)
    except Exception as error:
        result["identity_complete"] = False
        _warn_into(diagnostics, "walk", error)
    result["elements"] = elements
    return _strip(result)


def _strip(result: dict) -> dict:
    """Fold the bound helper's findings back in; neither must escape as data."""
    diagnostics = result["tree_diagnostics"]
    diagnostics.pop("warn", None)
    if diagnostics.pop("identity_broken", False):
        result["identity_complete"] = False
    return result


def read(hwnd: int, timeout_ms: int = DEFAULT_TIMEOUT_MS, max_elements: int = DEFAULT_MAX_ELEMENTS):
    """Walk one window's tree. Returns (elements, timed_out); the old contract."""
    detailed = read_detailed(hwnd, timeout_ms, max_elements)
    return detailed["elements"], detailed["timed_out"]


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
    return loose[0] if loose else None


def unique(matches: list[dict]) -> dict | None:
    """The one candidate, or None when there is not exactly one."""
    return matches[0] if len(matches) == 1 else None


def target_error(target: str | dict) -> str | None:
    """Validate plain target data before any provider or message is reached."""
    if isinstance(target, str):
        return None
    if not isinstance(target, dict):
        return "target must be a string or a selector object"
    unknown = set(target) - {"name", "automation_id", "control_type", "native_hwnd", "rect"}
    if unknown:
        return f"unsupported selector fields: {unknown!r}"
    for field in ("name", "automation_id", "control_type"):
        if field in target and not isinstance(target[field], str):
            return f"{field} must be a string"
    if "native_hwnd" in target and (type(target["native_hwnd"]) is not int
                                    or target["native_hwnd"] <= 0):
        return "native_hwnd must be a positive integer, not a bool"
    if not any(target.get(field, "").strip()
               for field in ("name", "automation_id", "control_type")) \
            and "native_hwnd" not in target:
        return "selector needs a non-empty name, automation_id, control_type or native_hwnd"
    if "rect" in target:
        rect = target["rect"]
        if not isinstance(rect, list) or len(rect) != 4 \
                or any(type(value) is not int for value in rect) \
                or rect[2] <= 0 or rect[3] <= 0:
            return "rect must be [x, y, width, height] integers with positive width and height"
    return None


def resolve(detailed: dict, target: str | dict, *, exact_only: bool = False) -> dict:
    """Turn one target into a unique element, or say why it cannot.

    Selectors AND exact fields. String layers run AutomationId -> name -> (unless exact_only) name
    substring. Each layer must yield exactly one candidate: "take the first"
    is how a click lands on the wrong control.
    """
    error = target_error(target)
    if error:
        return {"ok": False, "reason": "invalid target", "detail": error}
    if target == "":
        return {"ok": False, "reason": "target required",
                "detail": "an empty target cannot select a control"}
    if detailed.get("timed_out") or detailed.get("limit_reached") \
            or not detailed.get("identity_complete"):
        return {"ok": False, "reason": "tree incomplete",
                "detail": "the tree was truncated, timed out or unreadable"}
    elements = [e for e in detailed.get("elements", []) if "_el" in e]
    if isinstance(target, dict):
        diagnostics = detailed.get("tree_diagnostics", {})
        # An unreadable rect/type/handle can hide another matching candidate.
        if diagnostics.get("warnings_truncated") or any(
                warning.get("stage") in target for warning in diagnostics.get("warnings", [])):
            return {"ok": False, "reason": "tree incomplete",
                    "detail": "a selector field could not be read for every control"}
        layers = [("selector", lambda e: all(e.get(key) == value for key, value in target.items()))]
    else:
        layers = [("automation_id", lambda e: e["automation_id"] == target),
                  ("name", lambda e: e["name"] == target)]
        if not exact_only:
            low = target.casefold()
            layers.append(("name substring",
                           lambda e: bool(e["name"]) and low in e["name"].casefold()))
    for label, predicate in layers:
        matches = [e for e in elements if predicate(e)]
        if len(matches) == 1:
            return {"ok": True, "element": matches[0], "matched": label}
        if len(matches) > 1:
            return {"ok": False, "reason": "ambiguous target",
                    "detail": f"{len(matches)} controls match {target!r} by {label}"}
    return {"ok": False, "reason": "no such control",
            "detail": f"nothing in this window is named {target!r}"}


_TEXT_RANGE = TextRange
