"""Explicit live MCP test against the owned WPF fixture; never run by unittest.

Start tests/fixtures/itemcontainer.ps1 with -RunDirectory <dir>, then run:
  python tests/live_itemcontainer.py --ready <dir>/ready.json --out <dir>/result.json
Only synthetic fixture items are read. This script closes only its own UIA worker.
"""

import argparse
import asyncio
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastmcp import Client
from deskweft import server, uia_worker, win32


async def run(info, results):
    hwnd = info["hwnd"]
    pid = wintypes.DWORD()
    win32.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    assert pid.value == info["pid"], "fixture window no longer belongs to recorded process"
    assert win32.title(hwnd) == "deskweft ItemContainer synthetic fixture", "wrong fixture window"
    assert info["initially_realized_count"] < info["item_count"]
    target = info["selector"]
    async with Client(server.mcp) as client:
        async def query(label, **arguments):
            began = time.monotonic()
            response = await client.call_tool("find_items", {"hwnd": hwnd, "target": target, **arguments})
            data = json.loads(response.content[0].text)
            results[label] = {"wall_ms": round((time.monotonic() - began) * 1000, 1), **data}
            return data

        identities = {}
        runtime_ids = {}
        runtime_changes = 0
        names = {}
        count = info["item_count"]
        for offset in range(0, count, 99):
            page = await query(f"page_{offset}", start_index=offset, max_items=100, timeout_ms=15000)
            assert page["ok"], page
            for item in page["items"]:
                index = item["index"]
                identity = item["automation_id"]
                runtime = tuple(item["runtime_id"] or ())
                assert runtime, "live fixture must provide runtime IDs"
                assert index not in identities or identities[index] == identity, "overlap changed"
                if index in runtime_ids and runtime_ids[index] != runtime:
                    runtime_changes += 1
                identities[index] = identity
                runtime_ids[index] = runtime
                names[index] = item["name"]
            assert not page["foreground_changed"], page
        assert len(identities) == count, (len(identities), count)
        assert len(set(identities.values())) == count
        assert sum(name == info["duplicate_label"] for name in names.values()) == info["duplicate_count"]
        assert names[count - 1] == info["far_label"]
        assert page["reached_end"] and not page["has_more"]
        assert not page["complete"], "a final offset page is not the complete query"

        far = await query("far_name", property_id=30005, value=info["far_label"])
        assert far["ok"] and far["reached_end"] and len(far["items"]) == 1, far
        assert far["items"][0]["name"] == info["far_label"]
        duplicates = await query("duplicates", property_id=30005, value=info["duplicate_label"])
        assert duplicates["ok"] and duplicates["reached_end"], duplicates
        assert len(duplicates["items"]) == info["duplicate_count"], duplicates
        missing = await query("missing", property_id=30005, value="Fixture absent item")
        assert missing["ok"] and missing["complete"] and not missing["items"], missing
        selected = await query("unselected_bool", property_id=30079, value=False, max_items=2)
        assert selected["ok"] and len(selected["items"]) == 2, selected
        # Provider capability evidence, not an assertion that it must support every property.
        await query("far_automation_id", property_id=30011, value=info["far_key"])
        timeout = await query("timeout", timeout_ms=1)
        assert not timeout["ok"] and timeout["execution_state"] == "unknown", timeout
        recovery = await query("recovery", property_id=30005, value=info["far_label"])
        assert recovery["ok"] and len(recovery["items"]) == 1, recovery
        results["verified"] = {"known_item_count": count, "unique_fixture_ids": len(set(identities.values())),
                               "duplicate_names_preserved": info["duplicate_count"],
                               "overlapping_pages_agreed": True,
                               "cross_call_runtime_id_changes": runtime_changes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    info = json.loads(args.ready.read_text(encoding="utf-8-sig"))
    results = {"fixture": info}
    try:
        asyncio.run(run(info, results))
        results["passed"] = True
    finally:
        uia_worker.close()
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": results.get("passed", False), "results": str(args.out),
                          "verified": results.get("verified")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
