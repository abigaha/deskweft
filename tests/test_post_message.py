"""post_message: bounded sync, async queueing, managed text buffers.

All Win32 calls are mocked here. Nothing sends a message to a real window.
"""

from __future__ import annotations

import ctypes
import unittest
from unittest import mock

from deskweft import win32

WM_GETTEXT = 0x000D
WM_SETTEXT = 0x000C
WM_GETTEXTLENGTH = 0x000E
BM_CLICK = 0x00F5
BM_GETCHECK = 0x00F0
CB_GETCURSEL = 0x0147


def _copy_gettext(text, wparam, lparam):
    raw = text.encode("utf-16-le", "surrogatepass")[:max(0, wparam - 1) * 2]
    ctypes.memmove(lparam, raw + b"\x00\x00", len(raw) + 2)
    return len(raw) // 2


class PostCase(unittest.TestCase):
    def setUp(self):
        for name, value in (("title", "Window"), ("class_name", "Edit"), ("foreground", 1)):
            patch = mock.patch.object(win32, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        is_window = mock.patch.object(win32.user32, "IsWindow", return_value=1)
        is_window.start()
        self.addCleanup(is_window.stop)
        # The target window belongs to another process unless a test says so.
        self.window_pid = 9999
        pid = mock.patch.object(win32, "_window_pid",
                                side_effect=lambda hwnd: self.window_pid)
        pid.start()
        self.addCleanup(pid.stop)
        self.child = 777

    def send_scalar(self, result=1, completed=True, error=0):
        return mock.patch.object(win32, "_send_scalar",
                                 return_value=(int(completed), result, error))


class TestValidation(PostCase):
    def test_invalid_handles(self):
        for bad in (0, -1, 0xFFFF, -2, True, "1"):
            result = win32.post_message(bad, WM_NULL, wait=True)
            self.assertFalse(result["ok"], bad)
            self.assertEqual(result["reason"], "invalid hwnd", bad)

    def test_broadcast_message_is_refused(self):
        result = win32.post_message(0xFFFF, 0, wait=True)
        self.assertFalse(result["ok"])

    def test_bool_and_out_of_range_scalars(self):
        cases = [
            dict(msg=True),
            dict(msg=-1),
            dict(msg=0x10000),
            dict(wparam=-1),
            dict(wparam=2 ** 64),
            dict(lparam=2 ** 63),
            dict(timeout_ms=0),
            dict(timeout_ms=30001),
            dict(timeout_ms=True),
            dict(max_chars=0),
            dict(max_chars=65537),
        ]
        for kwargs in cases:
            msg = kwargs.pop("msg", WM_NULL)
            result = win32.post_message(self.child, msg, **kwargs)
            self.assertFalse(result["ok"], kwargs)
            self.assertEqual(result["reason"], "invalid arguments", kwargs)

    def test_same_process_window_is_refused_in_sync_mode(self):
        self.window_pid = win32.os.getpid()
        result = win32.post_message(self.child, WM_NULL, wait=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "same process")

    def test_unmanaged_payload_messages_are_refused_even_with_unsafe(self):
        for msg in (0x004A, 0x0233):
            result = win32.post_message(self.child, msg, allow_unsafe=True,
                                        allow_foreground=True, wait=False)
            self.assertFalse(result["ok"], msg)
            self.assertEqual(result["reason"], "message payload unsupported")

    def test_unknown_scalar_needs_unsafe_and_permission(self):
        unknown = 0x0400
        self.assertEqual(win32.post_message(self.child, unknown)["reason"],
                         "unsafe message")
        self.assertTrue(win32.post_message(self.child, unknown, allow_unsafe=True)
                        ["needs_permission"])
        with mock.patch.object(win32, "_send_scalar", return_value=(1, 0, 0)) as send:
            result = win32.post_message(self.child, unknown, allow_unsafe=True,
                                        allow_foreground=True)
        self.assertTrue(result["ok"], result)
        send.assert_called_once()

    def test_query_requires_wait(self):
        result = win32.post_message(self.child, WM_GETTEXTLENGTH, wait=False)
        self.assertEqual(result["reason"], "query requires wait")

    def test_control_class_must_match_for_checkbox_and_lists(self):
        with mock.patch.object(win32, "class_name", return_value="Edit"):
            for msg in (BM_GETCHECK, CB_GETCURSEL):
                result = win32.post_message(self.child, msg, wait=True)
                self.assertEqual(result["reason"], "control class mismatch", msg)

    def test_setter_needs_permission(self):
        with self.send_scalar() as send:
            denied = win32.post_message(self.child, BM_CLICK)
        self.assertTrue(denied["needs_permission"])
        self.assertEqual(denied["execution_state"], "not_started")
        send.assert_not_called()
        with mock.patch.object(win32, "class_name", return_value="Button"), \
             self.send_scalar(0) as send:
            allowed = win32.post_message(self.child, BM_CLICK, allow_foreground=True)
        self.assertEqual(allowed["delivery"], "returned")
        send.assert_called_once()

    def test_input_messages_need_permission(self):
        """Synthesised mouse and keyboard input is a side effect like any other.

        These are in the known-scalar set because they carry no pointer, but a
        click or a keystroke changes the application - the permission gate has
        to cover them, or any caller can type into any window for free.
        """
        for msg in (0x0201, 0x0202, 0x020A, 0x0100, 0x0101, 0x0102):
            with self.send_scalar() as send:
                denied = win32.post_message(self.child, msg)
            self.assertTrue(denied.get("needs_permission"), hex(msg))
            self.assertEqual(denied["execution_state"], "not_started", hex(msg))
            send.assert_not_called()
            with self.send_scalar(0) as send:
                allowed = win32.post_message(self.child, msg, allow_foreground=True)
            self.assertEqual(allowed["delivery"], "returned", hex(msg))
            send.assert_called_once()

    def test_input_messages_never_queue_without_permission(self):
        for msg in (0x0201, 0x020A, 0x0102):
            with mock.patch.object(win32.user32, "PostMessageW") as post:
                denied = win32.post_message(self.child, msg, wait=False)
            self.assertTrue(denied.get("needs_permission"), hex(msg))
            post.assert_not_called()


class TestManagedText(PostCase):
    def fake_send_text(self, written=None, result=None, completed=True, error=0, capture=None):
        def send(hwnd, msg, wp, lp, timeout_ms):
            if capture is not None:
                capture.update(hwnd=hwnd, msg=msg, wp=wp, lp=lp, timeout_ms=timeout_ms)
            copied = _copy_gettext(written, wp, lp) if written is not None and msg == WM_GETTEXT else 1
            return int(completed), copied if result is None else result, error

        return mock.patch.object(win32, "_send_scalar", side_effect=send)

    def test_gettext_returns_text_and_reports_truncation(self):
        with self.fake_send_text("hello", result=5) as send:
            result = win32.post_message(self.child, WM_GETTEXT, wait=True, max_chars=64)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["text"], "hello")
        self.assertEqual(result["result"], 5)
        self.assertEqual(result["capacity"], 64)
        self.assertFalse(result["possibly_truncated"])
        self.assertEqual(result["execution_state"], "completed")

    def test_gettext_requires_clean_wparam_and_text(self):
        self.assertEqual(win32.post_message(self.child, WM_GETTEXT, wparam=1)["reason"],
                         "invalid arguments")
        self.assertEqual(win32.post_message(self.child, WM_GETTEXT, lparam=1)["reason"],
                         "invalid arguments")
        self.assertEqual(win32.post_message(self.child, WM_GETTEXT, text="x")["reason"],
                         "invalid arguments")

    def test_gettext_zero_is_an_empty_string(self):
        with self.fake_send_text("", result=0):
            result = win32.post_message(self.child, WM_GETTEXT, wait=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "")

    def test_gettext_uses_its_advertised_character_capacity_and_flags_truncation(self):
        for capacity, wanted in ((1, "a"), (3, "abc")):
            with self.subTest(capacity=capacity), self.fake_send_text("abcdef"):
                result = win32.post_message(self.child, WM_GETTEXT,
                                            wait=True, max_chars=capacity)
                self.assertEqual(result["text"], wanted)
                self.assertTrue(result["possibly_truncated"], result)

    def test_gettext_repairs_and_flags_a_truncated_surrogate_pair(self):
        with self.fake_send_text("a🙂b"):
            result = win32.post_message(self.child, WM_GETTEXT, wait=True, max_chars=2)
        self.assertEqual(result["text"], "a�")
        self.assertTrue(result["text_repaired"], result)
        self.assertTrue(result["possibly_truncated"], result)

    def test_settext_does_not_verify_only_a_matching_prefix(self):
        for requested, actual in (("abc", "abcdef"), ("", "kept")):
            with self.subTest(requested=requested), self.fake_send_text(actual):
                result = win32.post_message(self.child, WM_SETTEXT, text=requested,
                                            allow_foreground=True, wait=True)
                self.assertFalse(result["effect_verified"], result)
                self.assertEqual(result.get("verification_reason"), "readback incomplete")

    def test_gettext_result_beyond_capacity_is_rejected(self):
        with self.fake_send_text("", result=99):
            result = win32.post_message(self.child, WM_GETTEXT, wait=True, max_chars=8)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "invalid message result")

    def test_settext_needs_permission_even_though_it_is_managed(self):
        """Managed means "no pointer crosses the protocol", not "read-only".

        A managed write is still a write, and must be refused before it is sent.
        """
        with self.fake_send_text("x", result=1) as send:
            denied = win32.post_message(self.child, WM_SETTEXT, text="x", wait=True)
        self.assertFalse(denied["ok"])
        self.assertTrue(denied.get("needs_permission"))
        self.assertEqual(denied["execution_state"], "not_started")
        send.assert_not_called()

    def test_gettext_is_allowed_in_the_background(self):
        with self.fake_send_text("hello", result=5):
            allowed = win32.post_message(self.child, WM_GETTEXT, wait=True, max_chars=32)
        self.assertTrue(allowed["ok"], allowed)

    def test_lone_surrogate_is_repaired_and_flagged(self):
        with self.fake_send_text("\ud83d", result=1):
            result = win32.post_message(self.child, WM_GETTEXT, wait=True)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["text_repaired"])
        self.assertNotIn("\ud83d", result["text"])

    def test_settext_rejects_bad_text(self):
        for text in ("a\x00b", None, 5):
            result = win32.post_message(self.child, WM_SETTEXT, text=text, wait=True)
            self.assertEqual(result["reason"], "invalid arguments", repr(text))
        self.assertEqual(
            win32.post_message(self.child, WM_SETTEXT, text="x", wparam=3)["reason"],
            "invalid arguments")

    def test_settext_too_long_is_rejected_in_utf16_units(self):
        emoji = "🙂" * 40000  # 80000 UTF-16 units, 40000 Python characters
        result = win32.post_message(self.child, WM_SETTEXT, text=emoji,
                                    allow_foreground=True, wait=True)
        self.assertEqual(result["reason"], "invalid arguments")

    def test_settext_zero_result_is_a_refusal(self):
        with self.fake_send_text("", result=0):
            result = win32.post_message(self.child, WM_SETTEXT, text="x",
                                        allow_foreground=True, wait=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "control rejected text")
        self.assertEqual(result["execution_state"], "completed")

    def test_settext_verifies_by_reading_back_within_the_same_budget(self):
        seen = []

        def send(hwnd, msg, wp, lp, timeout_ms):
            seen.append((msg, timeout_ms))
            if msg == WM_SETTEXT:
                return 1, 1, 0
            return 1, _copy_gettext("new text", wp, lp), 0

        with mock.patch.object(win32, "_send_scalar", side_effect=send), \
             mock.patch.object(win32.time, "monotonic", side_effect=[0.0, 0.1, 0.9]):
            result = win32.post_message(self.child, WM_SETTEXT, text="new text",
                                        allow_foreground=True, wait=True, timeout_ms=1000)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["effect_verified"])
        self.assertEqual(result["delivery"], "returned")
        self.assertEqual([m for m, _ in seen], [WM_SETTEXT, WM_GETTEXT])
        self.assertLessEqual(seen[1][1], 1000)

    def test_settext_mismatch_is_a_failure_but_still_completed(self):
        def send(hwnd, msg, wp, lp, timeout_ms):
            if msg == WM_SETTEXT:
                return 1, 1, 0
            return 1, _copy_gettext("other", wp, lp), 0

        with mock.patch.object(win32, "_send_scalar", side_effect=send):
            result = win32.post_message(self.child, WM_SETTEXT, text="wanted",
                                        allow_foreground=True, wait=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "text readback mismatch")
        self.assertEqual(result["execution_state"], "completed")

    def test_settext_budget_exhausted_is_not_a_failure(self):
        with self.fake_send_text("", result=1), \
             mock.patch.object(win32.time, "monotonic", side_effect=[0.0, 1.0]):
            result = win32.post_message(self.child, WM_SETTEXT, text="x",
                                        allow_foreground=True, wait=True, timeout_ms=10)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["delivery"], "returned")
        self.assertFalse(result["effect_verified"])
        self.assertEqual(result["verification_reason"], "budget exhausted")

    def test_long_text_is_verified_in_full_not_against_a_short_preview(self):
        long_text = "字" * 5000

        def send(hwnd, msg, wp, lp, timeout_ms):
            if msg == WM_SETTEXT:
                return 1, 1, 0
            return 1, _copy_gettext(long_text, wp, lp), 0

        with mock.patch.object(win32, "_send_scalar", side_effect=send):
            result = win32.post_message(self.child, WM_SETTEXT, text=long_text,
                                        allow_foreground=True, wait=True)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["effect_verified"])

    def test_readback_that_cannot_fit_is_incomplete_not_a_mismatch(self):
        written = "字" * 5002

        def send(hwnd, msg, wp, lp, timeout_ms):
            if msg == WM_SETTEXT:
                return 1, 1, 0
            return 1, _copy_gettext(written, wp, lp), 0

        with mock.patch.object(win32, "_send_scalar", side_effect=send):
            result = win32.post_message(self.child, WM_SETTEXT, text="字" * 5001,
                                        allow_foreground=True, wait=True)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["effect_verified"])
        self.assertEqual(result["verification_reason"], "readback incomplete")


class TestResults(PostCase):
    def test_async_success_reports_only_queued(self):
        with mock.patch.object(win32.user32, "PostMessageW", return_value=1) as post:
            result = win32.post_message(self.child, 0x0400, allow_unsafe=True,
                                        allow_foreground=True, wait=False)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["delivery"], "queued")
        self.assertNotIn("result", result)
        self.assertFalse(result["effect_verified"])
        self.assertIn("foreground_before", result)
        self.assertIn("foreground_changed", result)
        post.assert_called_once()

    def test_async_failure_is_not_reported_as_queued(self):
        with mock.patch.object(win32.user32, "PostMessageW", return_value=0):
            result = win32.post_message(self.child, 0x0400, allow_unsafe=True,
                                        allow_foreground=True, wait=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "message delivery failed")

    def test_timeout_is_unknown_and_not_retried(self):
        with self.send_scalar(0, completed=False, error=1460):
            result = win32.post_message(self.child, 0, wait=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "message timed out")
        self.assertEqual(result["execution_state"], "unknown")
        self.assertFalse(result["retry_safe"])
        self.assertFalse(result["effect_verified"])

    def test_other_api_failure_keeps_the_error_code(self):
        with self.send_scalar(0, completed=False, error=5):
            result = win32.post_message(self.child, 0, wait=True)
        self.assertEqual(result["reason"], "message delivery failed")
        self.assertEqual(result["error"], 5)
        self.assertEqual(result["execution_state"], "unknown")

    def test_zero_api_failure_does_not_invent_a_timeout(self):
        with self.send_scalar(0, completed=False, error=0):
            result = win32.post_message(self.child, 0, wait=True)
        self.assertEqual(result["reason"], "message delivery failed")
        self.assertNotIn("timed out", result["reason"])

    def test_scalar_result_is_pointer_sized_signed(self):
        with mock.patch.object(win32, "class_name", return_value="ComboBox"), \
             self.send_scalar(-1):
            result = win32.post_message(self.child, CB_GETCURSEL, wait=True,
                                        allow_foreground=True)
        # -1 from a control is a legal "nothing selected", not a huge unsigned value.
        self.assertEqual(result["selection_index"], -1)
        self.assertEqual(result["result"], -1)

    def test_gettextlength_only_reports_a_length(self):
        with self.send_scalar(12):
            result = win32.post_message(self.child, WM_GETTEXTLENGTH, wait=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], 12)
        self.assertNotIn("text", result)


WM_NULL = 0x0000


if __name__ == "__main__":
    unittest.main()
