"""Read the 150 synthetic files in an owned Explorer fixture through real MCP.

Requires the ownership manifest from the documented Explorer fixture launcher.
Pass --content-hwnd only after verifying the UIItemsView belongs to that window.
Never run through unittest; closes only this script's own worker.
"""

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastmcp import Client
from deskweft import server, uia_worker, win32


async def run(info, content_hwnd, results):
    hwnd = info["hwnd"]
    assert win32.class_name(hwnd) == "CabinetWClass", "fixture window no longer exists"
    assert win32.user32.IsChild(hwnd, content_hwnd), "content window has changed ownership"
    folder = Path(info["folder"])
    files = list(folder.iterdir())
    assert len(files) == info["item_count"] == 150
    assert all(file.name.startswith("fixture-") and file.stat().st_size == 0 for file in files)
    expected = {file.name for file in files}
    stems = {file.stem for file in files}
    target = {"native_hwnd": content_hwnd, "control_type": "ListControl"}
    async with Client(server.mcp) as client:
        async def query(label, **args):
            began = time.monotonic()
            response = await client.call_tool("find_items", {"hwnd": hwnd, "target": target, **args})
            data = json.loads(response.content[0].text)
            results[label] = {"wall_ms": round((time.monotonic() - began) * 1000, 1), **data}
            return data
        first = await query("page_0", max_items=100, timeout_ms=15000)
        assert first["ok"] and len(first["items"]) == 100 and first["has_more"], first
        last = await query("page_99", start_index=99, max_items=100, timeout_ms=15000)
        assert last["ok"] and last["reached_end"] and len(last["items"]) == 51, last
        assert first["items"][-1]["name"] == last["items"][0]["name"], "overlap changed"
        names = {item["name"] for item in first["items"] + last["items"]}
        assert names == expected or names == stems, (len(names), sorted(names)[:2])
        far_name = info["far_name"] if info["far_name"] in names else Path(info["far_name"]).stem
        far = await query("far_name", property_id=30005, value=far_name)
        assert far["ok"] and far["reached_end"] and len(far["items"]) == 1, far
        assert far["items"][0]["name"] == far_name
        missing = await query("missing", property_id=30005, value="fixture-absent-item")
        assert missing["ok"] and missing["complete"] and not missing["items"], missing
        response = await client.call_tool("find_items", {"hwnd": content_hwnd, "target": "", "max_items": 2})
        root = json.loads(response.content[0].text)
        results["verified_child_root"] = root
        assert root["ok"] and len(root["items"]) == 2, root
        for result in (first, last, far, missing, root):
            assert not result["foreground_changed"], result
        results["verified"] = {"known_empty_files": len(expected), "distinct_names": len(names),
                               "overlap_agreed": True, "far_name_filter": True,
                               "owned_child_root": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready", required=True, type=Path)
    parser.add_argument("--content-hwnd", required=True, type=int)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    info = json.loads(args.ready.read_text(encoding="utf-8-sig"))
    results = {"fixture": info, "content_hwnd": args.content_hwnd}
    try:
        asyncio.run(run(info, args.content_hwnd, results))
        results["passed"] = True
    finally:
        uia_worker.close()
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": results.get("passed", False), "results": str(args.out),
                          "verified": results.get("verified")}))


if __name__ == "__main__":
    main()
