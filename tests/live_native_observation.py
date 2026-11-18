"""Explicit MCP smoke test against two owned Win32 controls; never shows a window."""

import asyncio
import json
from pathlib import Path
import sys

import win32con
import win32gui
from fastmcp import Client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deskweft import server


async def verify():
    create = win32gui.CreateWindowEx
    parent = create(0, "STATIC", "DeskWeft native fixture", 0, 0, 0, 160, 90, 0, 0, 0, None)
    try:
        edit = create(0, "EDIT", "fixture only", win32con.WS_CHILD, 0, 0, 100, 20, parent, 1, 0, None)
        label = create(0, "STATIC", "fixture label", win32con.WS_CHILD, 0, 25, 100, 20, parent, 2, 0, None)
        assert not win32gui.IsWindowVisible(parent)
        async with Client(server.mcp) as client:
            for limit in (1, 2):
                reply = await client.call_tool("see", {"hwnd": parent, "native_only": True,
                                                       "max_elements": limit, "timeout_ms": 8000})
                assert [block.type for block in reply.content] == ["text"]
                data = json.loads(reply.content[0].text)
                assert data.get("ok"), data
                assert data["native_only"] and not ({"elements", "image_size", "image_unavailable"} & data.keys())
                rows = data["native_children"]
                assert len(rows) == limit and data["native_children_truncated"] == (limit == 1)
                assert all(row["hwnd"] in (edit, label) for row in rows)
                if limit == 2:
                    assert {row["hwnd"]: row["class"].lower() for row in rows} == {edit: "edit", label: "static"}
                assert not win32gui.IsWindowVisible(parent)
                print(f"limit={limit} children={len(rows)} truncated={data['native_children_truncated']} content=text")
    finally:
        win32gui.DestroyWindow(parent)
    assert not any(win32gui.IsWindow(hwnd) for hwnd in (parent, edit, label))
    print("Owned fixture destroyed")


if __name__ == "__main__":
    asyncio.run(verify())
