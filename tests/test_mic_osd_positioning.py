import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from mic_osd.positioning import CaretRect, compute_osd_position


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


if __name__ == "__main__":
    unittest.main()
