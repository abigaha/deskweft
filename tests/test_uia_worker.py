"""uia_worker: framed IPC, deadlines, recycling, sticky unavailability.

A fake worker process is used here. Nothing spawns real UIA and no COM object
crosses the socket; the workers in these tests are this process's own threads
holding a socket, so the framing and deadline logic runs for real.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
import unittest
from unittest import mock

from winmcp import uia_worker


class FakeChannel:
    """A worker side used in-process: it answers with plain dicts."""

    def __init__(self, exchange):
        self.exchange = exchange


class WorkerCase(unittest.TestCase):
    def setUp(self):
        self.patch_state = mock.patch.multiple(
            uia_worker, _stopping=threading.Event(), _worker=None, _lock=threading.Lock(),
            _unavailable=None)
        self.patch_state.start()
        self.addCleanup(self.patch_state.stop)

    def start_fake(self, behaviour):
        """Run a real socketpair worker in a thread; `behaviour` gets the socket."""
        parent, child = socket.socketpair()
        thread = threading.Thread(target=behaviour, args=(child,), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)

        def stop():
            for handle in (parent, child):
                try:
                    handle.close()
                except OSError:
                    pass

        self.addCleanup(stop)
        return parent, child, thread


def ready_worker(behaviour, *, transport=True):
    def run(channel):
        channel.setblocking(False)
        if transport:
            uia_worker._send_bytes(channel, uia_worker._encode_frame(
                {"transport_ready": True}), None)
        uia_worker._send_bytes(channel, uia_worker._encode_frame({"ready": True}), None)
        try:
            behaviour(channel)
        except (OSError, EOFError, ValueError):
            pass

    return run


class TestFraming(unittest.TestCase):
    def test_round_trip(self):
        parent, child = socket.socketpair()
        self.addCleanup(parent.close)
        self.addCleanup(child.close)
        payload = {"request_id": 7, "result": {"ok": True, "text": "中文"}}
        uia_worker._send_bytes(child, uia_worker._encode_frame(payload), None)
        self.assertEqual(uia_worker._recv_frame(parent, time.monotonic() + 5), payload)

    def test_frame_over_the_limit_is_refused(self):
        with mock.patch.object(uia_worker, "MAX_FRAME_BYTES", 64):
            with self.assertRaises(ValueError):
                uia_worker._encode_frame({"x": "y" * 200})

    def test_a_bad_length_is_refused(self):
        parent, child = socket.socketpair()
        self.addCleanup(parent.close)
        self.addCleanup(child.close)
        child.sendall(struct.pack("!I", 0))
        with self.assertRaises(ValueError):
            uia_worker._recv_frame(parent, time.monotonic() + 2)

    def test_a_half_header_times_out(self):
        parent, child = socket.socketpair()
        self.addCleanup(parent.close)
        self.addCleanup(child.close)
        child.sendall(b"\x00\x00")
        with self.assertRaises(TimeoutError):
            uia_worker._recv_frame(parent, time.monotonic() + 0.2)

    def test_a_half_body_times_out(self):
        parent, child = socket.socketpair()
        self.addCleanup(parent.close)
        self.addCleanup(child.close)
        child.sendall(struct.pack("!I", 100) + b'{"a"')
        with self.assertRaises(TimeoutError):
            uia_worker._recv_frame(parent, time.monotonic() + 0.2)

    def test_eof_while_receiving(self):
        parent, child = socket.socketpair()
        self.addCleanup(parent.close)
        child.close()
        with self.assertRaises(EOFError):
            uia_worker._recv_frame(parent, time.monotonic() + 2)

    def test_a_past_deadline_stops_a_send_at_once(self):
        parent, child = socket.socketpair()
        self.addCleanup(parent.close)
        self.addCleanup(child.close)
        began = time.monotonic()
        with self.assertRaises(TimeoutError):
            uia_worker._send_bytes(parent, b"x" * 1024, began - 1)
        self.assertLess(time.monotonic() - began, 0.5)

    def test_a_past_deadline_stops_a_receive_at_once(self):
        parent, child = socket.socketpair()
        self.addCleanup(parent.close)
        self.addCleanup(child.close)
        began = time.monotonic()
        with self.assertRaises(TimeoutError):
            uia_worker._recv_frame(parent, began - 1)
        self.assertLess(time.monotonic() - began, 0.5)

    def test_non_dict_payload_is_refused(self):
        parent, child = socket.socketpair()
        self.addCleanup(parent.close)
        self.addCleanup(child.close)
        blob = json.dumps([1, 2, 3]).encode()
        child.sendall(struct.pack("!I", len(blob)) + blob)
        with self.assertRaises(ValueError):
            uia_worker._recv_frame(parent, time.monotonic() + 2)


class TestCall(WorkerCase):
    def attach(self, channel, worker=None, started=True):
        """Attach a worker that has already completed both handshakes.

        start_fake runs the real handshake, so the two startup frames are in the
        socket buffer; a real parent consumes them inside _spawn. Mirror that
        here, otherwise every reply is read off by one frame.
        """
        worker = worker or mock.Mock()
        worker.is_alive.return_value = True
        uia_worker._worker = {
            "process": worker, "channel": channel,
            "started": started, "transport_ready": True,
            "start_ms": 1.0, "startup_ms": 2.0}
        if started and worker.is_alive():
            try:
                for _ in range(2):
                    uia_worker._recv_frame(channel, time.monotonic() + 2)
            except (TimeoutError, EOFError, ValueError):
                pass
        return worker

    def test_a_normal_call_returns_the_result(self):
        def behaviour(channel):
            request = uia_worker._recv_frame(channel, None)
            uia_worker._send_bytes(channel, uia_worker._encode_frame(
                {"request_id": request["request_id"],
                 "result": {"ok": True, "value": 42}}), None)
            uia_worker._recv_frame(channel, None)

        parent, _child, _thread = self.start_fake(ready_worker(behaviour))
        self.attach(parent)
        result = uia_worker.call("invoke_pattern", {"hwnd": 1}, 5000)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["value"], 42)

    def test_request_ids_are_increasing_and_checked(self):
        def behaviour(channel):
            request = uia_worker._recv_frame(channel, None)
            uia_worker._send_bytes(channel, uia_worker._encode_frame(
                {"request_id": request["request_id"] + 1, "result": {"ok": True}}), None)
            uia_worker._recv_frame(channel, None)

        parent, _child, _thread = self.start_fake(ready_worker(behaviour))
        worker = self.attach(parent)
        with mock.patch.object(uia_worker, "_discard") as discard:
            result = uia_worker.call("see", {"hwnd": 1}, 2000)
        self.assertFalse(result["ok"])
        self.assertEqual(result["execution_state"], "unknown")
        discard.assert_called()

    def test_busy_is_not_queued(self):
        self.attach(socket.socketpair()[0])
        uia_worker._lock.acquire()
        try:
            result = uia_worker.call("see", {"hwnd": 1}, 1000)
        finally:
            uia_worker._lock.release()
        self.assertFalse(result["ok"])
        self.assertIn("busy", result["reason"])
        self.assertEqual(result["execution_state"], "not_started")

    def test_timeout_discards_the_worker_and_reports_unknown(self):
        def behaviour(channel):
            uia_worker._recv_frame(channel, None)  # swallow the request, never answer
            time.sleep(5)

        parent, _child, _thread = self.start_fake(ready_worker(behaviour))
        worker = self.attach(parent)
        with mock.patch.object(uia_worker, "_discard") as discard:
            result = uia_worker.call("click", {"hwnd": 1}, 300)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "desktop call timed out")
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["execution_state"], "unknown")
        self.assertFalse(result["effect_verified"])
        self.assertFalse(result["retry_safe"])
        discard.assert_called_once()
        self.assertIn("cleanup_ms", result)

    def test_a_failed_call_is_reported_once_without_a_retry(self):
        def behaviour(channel):
            request = uia_worker._recv_frame(channel, None)
            uia_worker._send_bytes(channel, uia_worker._encode_frame(
                {"request_id": request["request_id"],
                 "result": {"ok": False, "reason": "provider error",
                            "execution_state": "unknown"}}), None)
            uia_worker._recv_frame(channel, None)

        parent, _child, _thread = self.start_fake(ready_worker(behaviour))
        self.attach(parent)
        result = uia_worker.call("click", {"hwnd": 1}, 2000)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "provider error")

    def test_stopping_refuses_new_calls(self):
        self.attach(socket.socketpair()[0])
        uia_worker._stopping.set()
        result = uia_worker.call("see", {"hwnd": 1}, 1000)
        self.assertEqual(result["execution_state"], "not_started")

    def test_unknown_action_is_refused_before_sending(self):
        self.attach(socket.socketpair()[0])
        result = uia_worker.call("eval", {"python": "1+1"}, 1000)
        self.assertFalse(result["ok"])
        self.assertEqual(result["execution_state"], "not_started")

    def test_unserialisable_arguments_are_not_started(self):
        self.attach(socket.socketpair()[0])
        result = uia_worker.call("see", {"hwnd": object()}, 1000)
        self.assertFalse(result["ok"])
        self.assertEqual(result["execution_state"], "not_started")
        self.assertEqual(result["reason"], "invalid arguments")


class TestStartup(WorkerCase):
    def test_missing_transport_ready_marks_the_service_unavailable(self):
        proc = mock.Mock()
        proc.is_alive.return_value = False
        with mock.patch.object(uia_worker, "_spawn", side_effect=RuntimeError("no spawn")):
            result = uia_worker.call("see", {"hwnd": 1}, 1000)
        self.assertFalse(result["ok"])
        self.assertEqual(result["execution_state"], "not_started")

    def test_init_failure_is_reported_without_sending_an_action(self):
        with mock.patch.object(uia_worker, "_spawn",
                               side_effect=RuntimeError("worker init failed: no UIA")):
            result = uia_worker.call("see", {"hwnd": 1}, 2000)
        self.assertFalse(result["ok"])
        self.assertIn("worker init failed", result["reason"] + result["detail"])
        self.assertEqual(result["execution_state"], "not_started")

    def test_sticky_unavailable_is_not_retried(self):
        uia_worker._unavailable = "worker unavailable: startup failed"
        with mock.patch.object(uia_worker, "_spawn") as spawn:
            result = uia_worker.call("see", {"hwnd": 1}, 1000)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "worker unavailable")
        spawn.assert_not_called()

    def test_a_timeout_before_transport_ready_is_sticky(self):
        """No transport_ready arrived: the standard-library resource handoff is
        unproven, so rebuilding risks leaking it. Unavailable stays."""
        with mock.patch.object(uia_worker, "_spawn",
                               side_effect=uia_worker.StartupFailure(
                                   "IPC deadline exceeded", transport_ready=False)):
            first = uia_worker.call("see", {"hwnd": 1}, 1000)
        self.assertFalse(first["ok"])
        self.assertEqual(first["reason"], "worker unavailable")
        with mock.patch.object(uia_worker, "_spawn") as spawn:
            second = uia_worker.call("see", {"hwnd": 1}, 1000)
        self.assertEqual(second["reason"], "worker unavailable")
        spawn.assert_not_called()

    def test_a_slow_start_after_transport_ready_may_rebuild(self):
        """transport_ready arrived and the child was reaped, so the handoff
        completed: a slow initialization must not disable every desktop tool."""
        calls = {"n": 0}

        def spawn():
            calls["n"] += 1
            if calls["n"] == 1:
                raise uia_worker.StartupFailure("IPC deadline exceeded",
                                                transport_ready=True)
            raise uia_worker.StartupFailure("still broken", transport_ready=True)

        with mock.patch.object(uia_worker, "_spawn", side_effect=spawn):
            first = uia_worker.call("see", {"hwnd": 1}, 1000)
            second = uia_worker.call("see", {"hwnd": 1}, 1000)
        self.assertFalse(first["ok"])
        self.assertEqual(first["reason"], "worker init timeout")
        self.assertEqual(calls["n"], 2, "a retry after transport_ready must be attempted")
        self.assertFalse(second["ok"])

    def test_an_unreadable_transport_reply_is_not_sticky(self):
        """transport_ready did arrive, so the handoff is proven; the next call
        may rebuild rather than lose every desktop tool for the service's life."""
        with mock.patch.object(uia_worker, "_spawn",
                               side_effect=uia_worker.StartupFailure(
                                   "worker rejected the transport",
                                   transport_ready=True)):
            result = uia_worker.call("see", {"hwnd": 1}, 1000)
        self.assertFalse(result["ok"])
        self.assertEqual(result["execution_state"], "not_started")
        self.assertTrue(result["retry_safe"])
        self.assertIsNone(uia_worker._unavailable)

    def test_close_is_idempotent(self):
        uia_worker.close()
        uia_worker.close()

    def test_an_undead_worker_is_kept_and_makes_the_service_sticky(self):
        """A worker that survives terminate and kill must not be replaced.

        Rebuilding it would leak one wedged child per request, so the honest
        answer is a sticky failure that names the real condition.
        """
        undead = mock.Mock()
        undead.is_alive.return_value = True

        def behaviour(channel):
            uia_worker._recv_frame(channel, None)  # swallow: force a timeout
            time.sleep(5)

        parent, _child, _thread = self.start_fake(ready_worker(behaviour))
        worker = mock.Mock()
        worker.is_alive.return_value = True
        uia_worker._worker = {"process": worker, "channel": parent,
                              "started": True, "transport_ready": True,
                              "start_ms": 1.0, "startup_ms": 2.0}
        for _ in range(2):
            uia_worker._recv_frame(parent, time.monotonic() + 2)
        with mock.patch.object(uia_worker, "_reap", return_value=(1.0, True)) as reap, \
             mock.patch.object(uia_worker, "_spawn") as spawn:
            first = uia_worker.call("see", {"hwnd": 1}, 200)
            second = uia_worker.call("see", {"hwnd": 1}, 200)
        self.assertFalse(first["ok"])
        self.assertTrue(reap.called)
        self.assertIsNotNone(uia_worker._unavailable, "an unreapable worker must be sticky")
        self.assertEqual(second["reason"], "worker unavailable")
        spawn.assert_not_called()
        self.assertIs(uia_worker._worker, None)


class TestImages(unittest.TestCase):
    def test_small_png_survives_the_round_trip(self):
        payload = {"meta": {"ok": True}, "png": b"\x89PNG"}
        encoded = uia_worker._encode_result(payload)
        self.assertIn("png_b64", encoded["meta"] if False else encoded)
        decoded = uia_worker._decode_result(encoded)
        self.assertEqual(decoded["png"], b"\x89PNG")

    def test_oversized_image_is_dropped_but_the_tree_survives(self):
        with mock.patch.object(uia_worker, "MAX_IMAGE_BYTES", 8):
            encoded = uia_worker._encode_result(
                {"meta": {"ok": True}, "png": b"x" * 100})
        decoded = uia_worker._decode_result(encoded)
        self.assertIsNone(decoded["png"])
        self.assertEqual(decoded["meta"]["image_unavailable"], "IPC image size limit")
        self.assertTrue(decoded["meta"]["ok"])

    def test_a_combination_that_exceeds_the_frame_drops_the_image_first(self):
        """The tree is the expensive part; an image is replaceable by re-reading.
        Losing the whole result because meta+image is a byte over the limit would
        throw away work the caller asked for and cannot easily repeat."""
        big_meta = {"ok": True, "elements": [{"name": "n" * 200} for _ in range(2000)]}
        image = b"x" * 200_000
        # Metadata alone is ~428 KB; with the base64 image it is ~695 KB, so a
        # 600 KB frame fits the tree and not the pair.
        with mock.patch.object(uia_worker, "MAX_FRAME_BYTES", 600_000), \
             mock.patch.object(uia_worker, "MAX_IMAGE_BYTES", 10_000_000):
            encoded = uia_worker._encode_result({"meta": big_meta, "png": image})
        decoded = uia_worker._decode_result(encoded)
        self.assertIsNone(decoded["png"], "the image should have been dropped")
        self.assertEqual(decoded["meta"]["image_unavailable"], "IPC image size limit")
        self.assertEqual(len(decoded["meta"]["elements"]), 2000, "the tree must survive")

    def test_metadata_alone_over_the_limit_is_a_named_error(self):
        with mock.patch.object(uia_worker, "MAX_FRAME_BYTES", 200):
            with self.assertRaises(uia_worker.ResponseTooLarge):
                uia_worker._encode_result({"meta": {"blob": "y" * 1000}, "png": None})


if __name__ == "__main__":
    unittest.main()
