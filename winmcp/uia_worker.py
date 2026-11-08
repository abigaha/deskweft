"""One recycling child process owns every desktop call.

Why a process: a synchronous MCP tool runs on a thread-pool thread, and UIA
objects are bound to the thread that created them. Worse, a wedged provider call
cannot be interrupted from Python - no timeout, no traversal budget, nothing
stops a COM call that never returns. So the reads, the actions and the generic
pattern call all happen in one worker process that this service may terminate.

What the parent may believe afterwards:
  - before sending: nothing ran (not_started)
  - after sending: the action may or may not have reached the application, so
    the result is `execution_state="unknown"` and is never retried by itself.

Only plain data crosses the socket: frames carry JSON, images travel as base64,
and a COM object never leaves the worker's thread.
"""

from __future__ import annotations

import base64
import json
import multiprocessing
import os
import select
import socket
import struct
import threading
import time

MAX_FRAME_BYTES = 32 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
STARTUP_MS = 5000
CLOSE_GRACE_MS = 1000

_ACTIONS = ("see", "click", "type_text", "key", "scroll", "invoke_pattern")

_stopping = threading.Event()
_lock = threading.Lock()
_worker: dict | None = None
_unavailable: str | None = None
_counter = 0


class ResponseTooLarge(Exception):
    """The result cannot be framed even without its image."""


class StartupFailure(Exception):
    """A worker could not be started.

    `transport_ready` says whether the standard-library handle handoff
    completed. Before it, the handoff is unproven and a rebuild risks leaking
    resources, so the service becomes sticky unavailable. After it, the child
    was reaped cleanly and a later call may legitimately build a new worker.
    """

    def __init__(self, detail: str, *, transport_ready: bool, reason: str = ""):
        super().__init__(detail)
        self.detail = detail
        self.transport_ready = transport_ready
        self.reason = reason or ("worker init timeout" if transport_ready
                                 else "worker unavailable")


# ---------- framing ----------


def _wait_io(channel: socket.socket, *, write: bool, deadline: float | None) -> None:
    while True:
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise TimeoutError("IPC deadline exceeded")
        readable, writable, _ = select.select(
            [] if write else [channel], [channel] if write else [], [], remaining)
        if readable or writable:
            return


def _send_bytes(channel: socket.socket, payload: bytes, deadline: float | None) -> None:
    pending = memoryview(payload)
    while pending:
        _wait_io(channel, write=True, deadline=deadline)
        try:
            count = channel.send(pending)
        except (BlockingIOError, InterruptedError):
            continue
        if count == 0:
            raise EOFError("worker connection closed while sending")
        pending = pending[count:]


def _recv_exact(channel: socket.socket, count: int, deadline: float | None) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        _wait_io(channel, write=False, deadline=deadline)
        try:
            chunk = channel.recv(min(65536, count - len(chunks)))
        except (BlockingIOError, InterruptedError):
            continue
        if not chunk:
            raise EOFError("worker connection closed while receiving")
        chunks.extend(chunk)
    return bytes(chunks)


def _encode_frame(message: dict) -> bytes:
    payload = json.dumps(message, ensure_ascii=True, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
    if not 0 < len(payload) <= MAX_FRAME_BYTES:
        raise ValueError("IPC frame exceeds limit")
    return struct.pack("!I", len(payload)) + payload


def _recv_frame(channel: socket.socket, deadline: float | None) -> dict:
    size, = struct.unpack("!I", _recv_exact(channel, 4, deadline))
    if not 0 < size <= MAX_FRAME_BYTES:
        raise ValueError("invalid IPC frame length")
    message = json.loads(_recv_exact(channel, size, deadline))
    if not isinstance(message, dict):
        raise ValueError("invalid IPC message")
    return message


# ---------- result encoding ----------


def _encode_result(result: dict) -> dict:
    """Turn {meta, png} into wire data: the image is base64, or dropped.

    An image is cheap to obtain again; the tree is not. So when the two together
    do not fit in a frame, the image goes and the tree is kept. Only metadata
    that cannot fit on its own is an error, and then it is a named one.
    """
    meta = dict(result.get("meta") or {})
    png = result.get("png")
    if not isinstance(meta, dict):
        raise ResponseTooLarge("worker result invalid")
    encoded = {"meta": meta, "png_b64": None}
    if isinstance(png, (bytes, bytearray)):
        if len(png) > MAX_IMAGE_BYTES:
            meta["image_unavailable"] = "IPC image size limit"
        else:
            encoded["png_b64"] = base64.b64encode(bytes(png)).decode("ascii")
            try:
                _encode_frame(dict(encoded))
            except ValueError:
                # Meta + image together overflow: retry without the picture.
                encoded["png_b64"] = None
                meta["image_unavailable"] = "IPC image size limit"
    try:
        _encode_frame(dict(encoded))
    except ValueError:
        # Metadata alone is too big; an image cannot be blamed for that.
        raise ResponseTooLarge("worker response too large") from None
    return encoded


def _decode_result(result: dict) -> dict:
    png = None
    encoded = result.get("png_b64")
    if isinstance(encoded, str):
        try:
            png = base64.b64decode(encoded.encode("ascii"), validate=False)
        except (ValueError, UnicodeEncodeError):
            png = None
    meta = result.get("meta")
    return {"meta": meta if isinstance(meta, dict) else {}, "png": png}


# ---------- worker process ----------


def _make_dispatch() -> dict:
    from . import act, tree

    return {
        "see": _see,
        "click": lambda hwnd, target="", allow_foreground=False:
            act.act(hwnd, "click", target=target, allow_foreground=allow_foreground),
        "type_text": lambda hwnd, target="", text="", allow_foreground=False:
            act.act(hwnd, "type", target=target, text=text,
                    allow_foreground=allow_foreground),
        "key": lambda hwnd, keys="", allow_foreground=False:
            act.act(hwnd, "key", text=keys, allow_foreground=allow_foreground),
        "scroll": lambda hwnd, target="", direction="down", allow_foreground=False:
            act.act(hwnd, "scroll", target=target, text=direction,
                    allow_foreground=allow_foreground),
        "invoke_pattern": act.invoke_pattern,
    }


def _valid_see(hwnd, with_tree, timeout_ms, max_elements) -> str | None:
    if (isinstance(hwnd, bool) or not isinstance(hwnd, int)
            or not 0 < hwnd < 0x10000000 or hwnd == 0xFFFF):
        return "hwnd must be one positive window handle, not a broadcast or sentinel"
    if not isinstance(with_tree, bool):
        return "with_tree must be a bool"
    for name, value, high in (("timeout_ms", timeout_ms, 30000),
                              ("max_elements", max_elements, 10000)):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= high:
            return f"{name} must be an integer in 1..{high}"
    return None


def _see(hwnd: int, with_tree: bool = False, timeout_ms: int = 1500,
         max_elements: int = 200) -> dict:
    """Capture one window and optionally its tree, inside the worker thread.

    This runs where the UIA context lives, so the COM objects it produces are
    projected here and only plain data leaves.
    """
    from . import tree, win32

    problem = _valid_see(hwnd, with_tree, timeout_ms, max_elements)
    if problem:
        return {"ok": False, "reason": "invalid arguments", "detail": problem,
                "execution_state": "not_started"}
    if not win32.user32.IsWindow(hwnd):
        return {"ok": False, "reason": "no such window", "detail": f"hwnd {hwnd} is gone",
                "execution_state": "not_started"}

    meta = {"ok": True, "hwnd": hwnd, "title": win32.title(hwnd),
            "class": win32.class_name(hwnd)}
    png = None
    grabbed = win32.grab(hwnd)
    if grabbed is None:
        meta["image_unavailable"] = (
            "PrintWindow returned a blank frame: GPU overlay, protected content, or minimised")
    else:
        data, width, height = grabbed
        meta["image_size"] = [width, height]
        png = data

    if with_tree:
        detailed = tree.read_detailed(hwnd, timeout_ms, max_elements)
        meta["elements"] = [{key: value for key, value in element.items() if key != "_el"}
                            for element in detailed["elements"]]
        meta["element_count"] = len(detailed["elements"])
        meta["timed_out"] = detailed["timed_out"]
        meta["limit_reached"] = detailed["limit_reached"]
        meta["identity_complete"] = detailed["identity_complete"]
        meta["tree_diagnostics"] = detailed["tree_diagnostics"]
        if detailed["timed_out"]:
            meta["tree_note"] = (f"stopped at {timeout_ms} ms - raise timeout_ms or "
                                 "target a smaller window")
        children = win32.children(hwnd)
        meta["native_children"] = children[:max_elements]
        meta["native_children_truncated"] = len(children) > max_elements
    return {"meta": meta, "png": png}


def _worker_main(channel) -> None:
    """The worker's whole life: init UIA, answer requests, come back as data."""
    from windows_mcp.uia import UIAutomationInitializerInThread

    try:
        channel.setblocking(False)
    except OSError:
        return
    try:
        _send_bytes(channel, _encode_frame({"transport_ready": True}), None)
    except (OSError, EOFError, ValueError):
        return

    try:
        context = UIAutomationInitializerInThread()
        dispatch = _make_dispatch()
    except Exception as error:
        try:
            _send_bytes(channel, _encode_frame(
                {"ready": False, "detail": f"{type(error).__name__}: {error}"}), None)
        except (OSError, EOFError, ValueError):
            pass
        return
    try:
        _send_bytes(channel, _encode_frame({"ready": True}), None)
    except (OSError, EOFError, ValueError):
        context.Uninitialize()
        return

    try:
        while True:
            try:
                request = _recv_frame(channel, None)
            except (EOFError, ValueError, OSError):
                return
            action = request.get("action")
            request_id = request.get("request_id")
            parameters = request.get("parameters")
            if action == "close":
                return
            if (action not in dispatch or isinstance(request_id, bool)
                    or not isinstance(request_id, int)
                    or not isinstance(parameters, dict)):
                _reply(channel, request_id, {
                    "ok": False, "reason": "invalid request",
                    "detail": "unknown action, request id or parameters",
                    "execution_state": "not_started", "retry_safe": True})
                continue
            try:
                result = dispatch[action](**parameters)
            except Exception as error:
                result = {"ok": False, "reason": "worker action failed",
                          "detail": f"{type(error).__name__}: {error}",
                          "execution_state": "unknown", "retry_safe": False}
            payload = _encode_payload(action, result)
            try:
                _send_bytes(channel, _encode_frame(
                    {"request_id": request_id, "result": payload}), None)
            except (OSError, EOFError, ValueError):
                # A half frame must not be followed by another frame.
                return
    finally:
        try:
            context.Uninitialize()
        except Exception:
            pass


def _encode_payload(action: str, result: dict) -> dict:
    if action == "see" and isinstance(result, dict) and "meta" in result:
        try:
            return _encode_result(result)
        except ResponseTooLarge as error:
            return {"ok": False, "reason": "worker response too large",
                    "detail": str(error), "call_completed": True,
                    "execution_state": "completed", "effect_verified": False,
                    "retry_safe": False}
    try:
        _encode_frame({"result": result})
    except ValueError:
        return {"ok": False, "reason": "worker result invalid",
                "detail": "the action returned data that is not JSON",
                "call_completed": True, "execution_state": "completed",
                "effect_verified": False, "retry_safe": False}
    return result


def _reply(channel, request_id, result: dict) -> None:
    try:
        _send_bytes(channel, _encode_frame(
            {"request_id": request_id, "result": result}), None)
    except (OSError, EOFError, ValueError):
        pass


# ---------- parent side ----------


def _spawn() -> dict:
    """Start the worker and complete both handshakes within one deadline."""
    context = multiprocessing.get_context("spawn")
    parent, child = socket.socketpair()
    parent.setblocking(False)
    proc = None
    handoff = False
    try:
        proc = context.Process(target=_worker_main, args=(child,), daemon=True)
        started = time.monotonic()
        proc.start()
        start_ms = round((time.monotonic() - started) * 1000, 1)
        child.close()  # the parent keeps only its own end
        deadline = time.monotonic() + STARTUP_MS / 1000
        first = _recv_frame(parent, deadline)
        if not first.get("transport_ready"):
            raise StartupFailure("worker rejected the transport", transport_ready=False)
        # From here the standard-library handoff is known to have completed, so
        # a failure below may safely be retried by a later call.
        handoff = True
        second = _recv_frame(parent, deadline)
        if second.get("ready") is not True:
            raise StartupFailure(second.get("detail") or "worker init failed",
                                 transport_ready=True, reason="worker init failed")
        return {"process": proc, "channel": parent, "started": True,
                "transport_ready": True, "start_ms": start_ms,
                "startup_ms": round((time.monotonic() - started) * 1000, 1)}
    except StartupFailure:
        _reap(proc, parent)
        raise
    except Exception as error:
        _reap(proc, parent)
        raise StartupFailure(f"{type(error).__name__}: {error}",
                             transport_ready=handoff) from None


def _reap(proc, channel) -> tuple[float, bool]:
    """Terminate, join, kill, join. Returns (ms spent, whether it survived).

    A survivor is a real condition, not a timing detail: the caller must stop
    creating workers, because each rebuild would leak another wedged child.
    """
    began = time.monotonic()
    if channel is not None:
        try:
            channel.close()
        except OSError:
            pass
    alive = False
    if proc is not None:
        try:
            if proc.is_alive():
                proc.terminate()
            proc.join(CLOSE_GRACE_MS / 1000)
            if proc.is_alive():
                proc.kill()
                proc.join(CLOSE_GRACE_MS / 1000)
            alive = bool(proc.is_alive())
        except Exception:
            alive = True
        if not alive:
            try:
                proc.close()
            except Exception:
                pass
    return round((time.monotonic() - began) * 1000, 1), alive


def _discard(reason: str) -> float:
    """Drop the current worker; the next call may build a fresh one.

    If the process survived both terminate and kill, it is kept referenced and
    the service goes sticky unavailable: leaking one wedged child per request
    is worse than an honest refusal that names the condition.
    """
    global _worker, _unavailable
    worker, _worker = _worker, None
    if worker is None:
        return 0.0
    elapsed, alive = _reap(worker.get("process"), worker.get("channel"))
    if alive:
        _unavailable = (f"worker unavailable: process {worker.get('process')} "
                        f"survived terminate and kill ({reason})")
    return elapsed


def _ensure() -> dict:
    global _worker, _unavailable
    if _unavailable:
        raise RuntimeError(_unavailable)
    if _worker is not None:
        process = _worker.get("process")
        if process is not None and process.is_alive():
            return _worker
        _discard("worker exited")
        if _unavailable:
            raise RuntimeError(_unavailable)
    _worker = _spawn()
    return _worker


def call(action: str, parameters: dict, timeout_ms: int) -> dict:
    """Run one action in the worker, bounded by `timeout_ms` for the whole call."""
    global _counter
    if action not in _ACTIONS:
        return {"ok": False, "reason": "invalid arguments",
                "detail": f"unknown action {action!r}", "execution_state": "not_started",
                "retry_safe": True}
    if _stopping.is_set():
        return _unavailable_result("stopping; no action was sent")
    try:
        request = json.loads(json.dumps({"action": action, "parameters": parameters,
                                         "request_id": 0}, allow_nan=False))
    except (TypeError, ValueError) as error:
        return {"ok": False, "reason": "invalid arguments",
                "detail": f"arguments are not JSON data: {error}",
                "execution_state": "not_started", "retry_safe": True}

    if not _lock.acquire(blocking=False):
        return {"ok": False, "reason": "worker busy",
                "detail": "another call is still running in the worker",
                "execution_state": "not_started", "retry_safe": True}
    cleanup_ms = 0.0
    try:
        if _stopping.is_set():
            return _unavailable_result("stopping; no action was sent")
        try:
            worker = _ensure()
        except RuntimeError as error:
            return _unavailable_result(str(error))
        except StartupFailure as error:
            if error.transport_ready:
                # The handoff completed and the child was reaped, so this is a
                # transient start problem: report it, let the next call retry,
                # and never leave every desktop tool permanently disabled.
                return {"ok": False, "reason": error.reason, "detail": error.detail,
                        "execution_state": "not_started", "effect_verified": False,
                        "retry_safe": True, "worker_restarted": False}
            _set_unavailable(error)
            return _unavailable_result(f"worker unavailable: {error.detail}")
        except Exception as error:
            _set_unavailable(error)
            return _unavailable_result(f"worker unavailable: {error}")

        _counter += 1
        request["request_id"] = _counter
        deadline = time.monotonic() + max(1, timeout_ms) / 1000
        try:
            encoded = _encode_frame(request)
        except ValueError as error:
            return {"ok": False, "reason": "invalid arguments", "detail": str(error),
                    "execution_state": "not_started", "retry_safe": True}
        try:
            _send_bytes(worker["channel"], encoded, deadline)
            reply = _recv_frame(worker["channel"], deadline)
        except TimeoutError:
            cleanup_ms = _discard("timeout")
            return _timeout_result(cleanup_ms)
        except (OSError, EOFError, ValueError) as error:
            cleanup_ms = _discard("protocol error")
            return {"ok": False, "reason": "worker connection lost",
                    "detail": f"{type(error).__name__}: {error}",
                    "execution_state": "unknown", "effect_verified": False,
                    "retry_safe": False, "worker_restarted": False,
                    "cleanup_ms": cleanup_ms}

        if reply.get("request_id") != request["request_id"]:
            cleanup_ms = _discard("stale frame")
            return {"ok": False, "reason": "worker response mismatch",
                    "detail": "a reply arrived for a different request",
                    "execution_state": "unknown", "effect_verified": False,
                    "retry_safe": False, "cleanup_ms": cleanup_ms}
        result = reply.get("result")
        if not isinstance(result, dict):
            cleanup_ms = _discard("invalid result")
            return {"ok": False, "reason": "worker result invalid",
                    "execution_state": "unknown", "effect_verified": False,
                    "retry_safe": False, "cleanup_ms": cleanup_ms}

        if action == "see" and "meta" in result:
            decoded = _decode_result(result)
            meta = decoded["meta"]
            meta["start_ms"] = worker.get("start_ms")
            meta["startup_ms"] = worker.get("startup_ms")
            meta["cleanup_ms"] = cleanup_ms
            return {"ok": bool(meta.get("ok")), "meta": meta, "png": decoded["png"]}
        result["cleanup_ms"] = cleanup_ms
        return result
    finally:
        _lock.release()


def _set_unavailable(error) -> None:
    global _unavailable
    _unavailable = f"worker unavailable: {type(error).__name__}: {error}"
    _discard("startup failed")


def _unavailable_result(detail: str) -> dict:
    return {"ok": False, "reason": "worker unavailable", "detail": detail,
            "execution_state": "not_started", "effect_verified": False,
            "retry_safe": True, "worker_restarted": False}


def _timeout_result(cleanup_ms: float) -> dict:
    return {"ok": False, "reason": "desktop call timed out",
            "detail": "UIA/Win32 worker exceeded its deadline and was discarded",
            "timed_out": True, "execution_state": "unknown",
            "effect_verified": False, "retry_safe": False,
            "worker_restarted": False, "cleanup_ms": cleanup_ms}


def close() -> None:
    """Stop the worker. New calls fail immediately instead of racing the close."""
    global _worker
    _stopping.set()
    if not _lock.acquire(timeout=CLOSE_GRACE_MS / 1000):
        # A live call owns the socket; its finally block sees `stopping` and
        # recycles the worker, so this must not touch it concurrently.
        return
    try:
        worker, _worker = _worker, None
        if worker is None:
            return
        channel = worker.get("channel")
        if channel is not None:
            try:
                _send_bytes(channel, _encode_frame({"action": "close"}),
                            time.monotonic() + CLOSE_GRACE_MS / 1000)
            except (OSError, EOFError, ValueError):
                pass
        _reap(worker.get("process"), channel)
    finally:
        _lock.release()
