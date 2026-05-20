import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from mic_osd import main as osd_main


class DummyWindow:
    def __init__(self):
        self.visible_values = []
        self.reset_count = 0
        self.layer_positions = []

    def reset_layer_position(self):
        self.reset_count += 1

    def set_visible(self, visible):
        self.visible_values.append(visible)

    def get_primary_monitor_size(self):
        return (1920, 1080)

    def set_layer_position(self, x, y):
        self.layer_positions.append((x, y))


def make_osd():
    osd = osd_main.MicOSD.__new__(osd_main.MicOSD)
    osd.audio_monitor = None
    osd.window = DummyWindow()
    osd.update_timer_id = None
    osd._auto_hide_timeout_id = None
    osd._state_poll_timer_id = None
    osd.visible = False
    osd._position_generation = 0
    osd._position_source_id = None
    osd._position_lookup_inflight = False
    osd._position_lookup_lock = threading.Lock()
    osd._use_file_audio = True
    osd.width = 200
    osd.height = 40
    return osd


class MicOSDAsyncPositioningTests(unittest.TestCase):
    def test_show_does_not_block_on_caret_lookup_or_stack_workers(self):
        osd = make_osd()
        lookup_entered = threading.Event()
        release_lookup = threading.Event()
        idle_added = threading.Event()
        lookup_calls = 0
        lookup_lock = threading.Lock()

        def blocking_caret_lookup():
            nonlocal lookup_calls
            with lookup_lock:
                lookup_calls += 1
            lookup_entered.set()
            release_lookup.wait(timeout=1)
            return None

        with (
            mock.patch.object(osd_main.GLib, "timeout_add", return_value=101),
            mock.patch.object(osd_main.GLib, "timeout_add_seconds", return_value=102),
            mock.patch.object(osd_main.GLib, "source_remove"),
            mock.patch.object(
                osd_main.GLib,
                "idle_add",
                side_effect=lambda callback: idle_added.set() or 103,
            ),
            mock.patch.object(osd_main, "get_focused_caret_rect", side_effect=blocking_caret_lookup),
        ):
            start = time.monotonic()
            osd._show()
            elapsed = time.monotonic() - start

            self.assertLess(elapsed, 0.1)
            self.assertEqual(osd.window.visible_values, [True])
            self.assertGreaterEqual(osd.window.reset_count, 1)
            self.assertTrue(lookup_entered.wait(timeout=0.5))

            osd._show()
            time.sleep(0.02)
            with lookup_lock:
                self.assertEqual(lookup_calls, 1)

            release_lookup.set()
            self.assertTrue(idle_added.wait(timeout=0.5))


if __name__ == "__main__":
    unittest.main()
