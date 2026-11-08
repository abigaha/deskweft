"""Bounded ItemContainer queries; element references never leave this worker call."""

import math
import time
from types import SimpleNamespace

from comtypes.automation import VARIANT
from windows_mcp.uia import ControlFromHandle, ControlsAreSame

from . import act, tree


def find_items(hwnd: int, target: str | dict = "", property_id: int = 0,
               value=None, start_index: int = 0, max_items: int = 100,
               timeout_ms: int = 8000) -> dict:
    """Find matching items, including virtualized items outside the visible tree.

    Each page rescans from NULL, keeping startAfter references in this call.
    Pages are live queries, not snapshots: callers must detect list changes.
    No Realize, scrolling, selection or focus operation is performed.
    """
    before = act.win32.foreground()
    started = time.perf_counter()
    if not act._valid_hwnd(hwnd):
        return act._fail("invalid hwnd", repr(hwnd), before)
    error = tree.target_error(target)
    if error:
        return act._fail("invalid target", error, before)
    for name, number, low, high in (
        ("property_id", property_id, 0, 2**31 - 1),
        ("start_index", start_index, 0, 10000),
        ("max_items", max_items, 1, act.MAX_ITEMS),
        ("timeout_ms", timeout_ms, 1, 30000),
    ):
        if type(number) is not int or not low <= number <= high:
            return act._fail("invalid arguments", f"{name} must be {low}..{high}", before)
    if property_id == 0:
        valid_value = value is None
    else:
        valid_value = (type(value) is bool
                       or type(value) is int and -(2**31) <= value < 2**31
                       or type(value) is float and math.isfinite(value)
                       or type(value) is str and len(value) <= act.MAX_TEXT)
    if not valid_value:
        return act._fail("invalid arguments", "property_id=0 needs value=null; other "
                         "properties need bool/int32/finite float/str (at most 6000 chars)", before)

    deadline = started + timeout_ms / 1000
    rows, seen, seen_ids, missing_ids = [], [], set(), []
    metadata_complete = True
    truncated = False
    chars_left = act.MAX_TEXT
    calls = 0
    reached_end = False
    has_more = None

    def finish(reason=None, detail="", *, state="unknown"):
        out = act._done(hwnd, "find_items", target, "uia:ItemContainerPattern", before,
                        started) if reason is None else act._fail(reason, detail, before, state=state)
        out.update(items=rows, start_index=start_index, property_id=property_id,
                   returned_count=len(rows), provider_calls=calls,
                   reached_end=reached_end, has_more=has_more,
                   next_start_index=(start_index + len(rows) if has_more else None),
                   metadata_complete=metadata_complete, result_truncated=truncated,
                   complete=(reason is None and start_index == 0 and reached_end
                             and metadata_complete and not truncated),
                   snapshot=False)
        return out

    try:
        if target == "":
            root = ControlFromHandle(hwnd)
            if root is None:
                return finish("no such control", "window has no UIA root", state="not_started")
        else:
            detailed = tree.read_detailed(hwnd, timeout_ms=min(3000, timeout_ms), max_elements=600)
            found = tree.resolve(detailed, target, exact_only=True)
            if not found["ok"]:
                return finish(found["reason"], found["detail"], state="not_started")
            root = found["element"]["_el"]
        pattern = tree.pattern_detailed(root, "ItemContainerPattern")
        if not pattern["ok"]:
            out = finish(pattern["reason"], pattern.get("detail", ""), state="not_started")
            out.update({k: pattern[k] for k in ("pattern_id", "cause_unknown") if k in pattern})
            return out
        # windows-mcp 0.8.8's wrapper dereferences control.Element even for NULL.
        provider = pattern["value"].pattern
        query = VARIANT() if property_id == 0 else VARIANT(value)
        previous = None
        for index in range(start_index + max_items + 1):
            if time.perf_counter() >= deadline:
                return finish("query budget exhausted", "deadline reached between provider calls")
            calls += 1
            current = provider.FindItemByProperty(previous, property_id, query)
            if not current:
                reached_end, has_more = True, False
                return finish()
            try:
                runtime_id = tuple(current.GetRuntimeId() or ())
            except Exception:
                runtime_id = ()
            duplicate = bool(runtime_id and runtime_id in seen_ids)
            if not duplicate:
                # A previous ID read may have failed even if this one succeeds.
                for old in (missing_ids if runtime_id else seen):
                    if time.perf_counter() >= deadline:
                        return finish("query budget exhausted", "deadline reached during identity checks")
                    if ControlsAreSame(SimpleNamespace(Element=current), SimpleNamespace(Element=old)):
                        duplicate = True
                        break
            if duplicate:
                return finish("provider cycle", "provider returned an already visited element")
            if runtime_id:
                seen_ids.add(runtime_id)
            else:
                missing_ids.append(current)
            seen.append(current)
            previous = current
            if index < start_index:
                continue
            if len(rows) == max_items:
                has_more = True
                return finish()
            row = {"index": index, "runtime_id": list(runtime_id) or None, "read_errors": {}}
            for key, attribute in (("name", "CurrentName"), ("automation_id", "CurrentAutomationId"),
                                   ("control_type", "CurrentControlType"),
                                   ("is_offscreen", "CurrentIsOffscreen")):
                try:
                    field = getattr(current, attribute)
                    if isinstance(field, str):
                        if len(field) > chars_left:
                            field = field[:chars_left]
                            truncated = True
                        chars_left -= len(field)
                    elif field is not None and type(field) not in (bool, int):
                        raise TypeError("unsupported property value")
                    row[key] = field
                except Exception as error:
                    row[key] = None
                    row["read_errors"][key] = f"{type(error).__name__}: {error}"[:160]
                    metadata_complete = False
            rows.append(row)
            if truncated:
                # Resume by re-reading this item: its metadata was only partial.
                out = finish()
                out["next_start_index"] = index
                return out
    except Exception as error:
        return finish("provider error", f"{type(error).__name__}: {error}")
