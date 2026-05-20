import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from mic_osd import positioning
from mic_osd.positioning import (
    CaretRect,
    MonitorGeometry,
    compute_osd_position,
    compute_osd_position_for_monitors,
)


class OSDPositioningTests(unittest.TestCase):
    def test_places_osd_centered_above_caret(self):
        pos = compute_osd_position(
            CaretRect(x=500, y=300, width=2, height=20),
            screen_width=1920,
            screen_height=1080,
            osd_width=200,
            osd_height=40,
            fixed_x=10,
            fixed_y=10,
        )
        self.assertEqual(pos, (401, 252))

    def test_clamps_horizontal_position_inside_screen(self):
        pos = compute_osd_position(
            CaretRect(x=5, y=300, width=2, height=20),
            screen_width=1920,
            screen_height=1080,
            osd_width=200,
            osd_height=40,
            fixed_x=10,
            fixed_y=10,
        )
        self.assertEqual(pos, (10, 252))

    def test_returns_none_when_caret_too_high_for_above_position(self):
        pos = compute_osd_position(
            CaretRect(x=500, y=20, width=2, height=20),
            screen_width=1920,
            screen_height=1080,
            osd_width=200,
            osd_height=40,
            fixed_x=10,
            fixed_y=10,
        )
        self.assertIsNone(pos)

    def test_returns_none_for_invalid_or_offscreen_caret(self):
        self.assertIsNone(
            compute_osd_position(
                CaretRect(x=-200, y=300, width=2, height=20),
                screen_width=1920,
                screen_height=1080,
                osd_width=200,
                osd_height=40,
            )
        )
        self.assertIsNone(
            compute_osd_position(
                CaretRect(x=500, y=1200, width=2, height=20),
                screen_width=1920,
                screen_height=1080,
                osd_width=200,
                osd_height=40,
            )
        )

    def test_returns_none_for_partially_offscreen_caret(self):
        self.assertIsNone(
            compute_osd_position(
                CaretRect(x=-0.5, y=300, width=2, height=20),
                screen_width=1920,
                screen_height=1080,
                osd_width=200,
                osd_height=40,
            )
        )
        self.assertIsNone(
            compute_osd_position(
                CaretRect(x=500, y=1070, width=2, height=20),
                screen_width=1920,
                screen_height=1080,
                osd_width=200,
                osd_height=40,
            )
        )

    def test_returns_none_when_osd_is_wider_than_usable_screen(self):
        self.assertIsNone(
            compute_osd_position(
                CaretRect(x=50, y=300, width=2, height=20),
                screen_width=100,
                screen_height=1080,
                osd_width=200,
                osd_height=40,
            )
        )

    def test_returns_none_when_no_caret_is_available(self):
        self.assertIsNone(
            compute_osd_position(
                None,
                screen_width=1920,
                screen_height=1080,
                osd_width=200,
                osd_height=40,
            )
        )

    def test_places_global_caret_on_matching_monitor(self):
        result = compute_osd_position_for_monitors(
            CaretRect(x=2500, y=500, width=2, height=20),
            monitors=[
                MonitorGeometry(x=0, y=0, width=1920, height=1080),
                MonitorGeometry(x=1920, y=0, width=1920, height=1080),
            ],
            osd_width=200,
            osd_height=40,
        )

        self.assertEqual(result, (1, 481, 452))

    def test_get_focused_caret_rect_skips_invalid_focused_text_and_searches_deeper(self):
        class FakeRect:
            def __init__(self, x, y, width, height):
                self.x = x
                self.y = y
                self.width = width
                self.height = height

        class FakeText:
            def __init__(self, offset, rect):
                self.offset = offset
                self.rect = rect

            def get_caret_offset(self):
                return self.offset

            def get_character_extents(self, _offset, _coord_type):
                return self.rect

        class FakeStateSet:
            def __init__(self, focused=False):
                self.focused = focused

            def contains(self, state):
                return self.focused and state == "focused"

        class FakeAccessible:
            def __init__(self, *, focused=False, text=None, children=None):
                self.focused = focused
                self.text = text
                self.children = children or []

            def get_state_set(self):
                return FakeStateSet(self.focused)

            def get_text_iface(self):
                return self.text

            def get_child_count(self):
                return len(self.children)

            def get_child_at_index(self, index):
                return self.children[index]

        class FakeAtspi:
            class StateType:
                FOCUSED = "focused"

            class CoordType:
                SCREEN = "screen"

            desktop = None

            @staticmethod
            def get_desktop(_index):
                return FakeAtspi.desktop

        valid_focused = FakeAccessible(
            focused=True,
            text=FakeText(3, FakeRect(300, 400, 2, 18)),
        )
        deep = valid_focused
        for _ in range(12):
            deep = FakeAccessible(children=[deep])

        invalid_focused_parent = FakeAccessible(
            focused=True,
            text=FakeText(-1, FakeRect(-1, -1, -1, -1)),
            children=[deep],
        )
        FakeAtspi.desktop = FakeAccessible(children=[invalid_focused_parent])

        with mock.patch.object(positioning, "_load_atspi", return_value=FakeAtspi):
            caret = positioning.get_focused_caret_rect(timeout=0.5)

        self.assertEqual(caret, CaretRect(x=300.0, y=400.0, width=2.0, height=18.0))

    def test_get_focused_caret_rect_honors_timeout_during_tree_walk(self):
        class FakeStateSet:
            def contains(self, _state):
                return False

        class FakeAccessible:
            def __init__(self, children=None):
                self.children = children or []

            def get_state_set(self):
                time.sleep(0.002)
                return FakeStateSet()

            def get_child_count(self):
                return len(self.children)

            def get_child_at_index(self, index):
                return self.children[index]

        class FakeAtspi:
            class StateType:
                FOCUSED = object()

            @staticmethod
            def get_desktop(_index):
                return FakeAccessible([FakeAccessible() for _ in range(100)])

        with mock.patch.object(positioning, "_load_atspi", return_value=FakeAtspi):
            start = time.monotonic()
            caret = positioning.get_focused_caret_rect(timeout=0.01)
            elapsed = time.monotonic() - start

        self.assertIsNone(caret)
        self.assertLess(elapsed, 0.08)


if __name__ == "__main__":
    unittest.main()
