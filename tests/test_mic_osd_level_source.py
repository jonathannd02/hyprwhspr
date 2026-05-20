import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from mic_osd.level_source import read_audio_level


class AudioLevelSourceTests(unittest.TestCase):
    def test_reads_fresh_level_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audio_level"
            path.write_text("0.372")
            self.assertEqual(read_audio_level(path, max_age_seconds=1.0), 0.372)

    def test_clamps_level_to_valid_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audio_level"
            path.write_text("4.5")
            self.assertEqual(read_audio_level(path, max_age_seconds=1.0), 1.0)
            path.write_text("-1.5")
            self.assertEqual(read_audio_level(path, max_age_seconds=1.0), 0.0)

    def test_returns_none_for_missing_invalid_or_stale_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            self.assertIsNone(read_audio_level(missing, max_age_seconds=1.0))

            invalid = Path(tmp) / "invalid"
            invalid.write_text("not-a-number")
            self.assertIsNone(read_audio_level(invalid, max_age_seconds=1.0))

            stale = Path(tmp) / "stale"
            stale.write_text("0.5")
            old = time.time() - 10
            os.utime(stale, (old, old))
            self.assertIsNone(read_audio_level(stale, max_age_seconds=1.0))

    def test_returns_none_for_non_finite_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audio_level"
            for value in ("nan", "inf", "-inf"):
                with self.subTest(value=value):
                    path.write_text(value)
                    self.assertIsNone(read_audio_level(path, max_age_seconds=1.0))


if __name__ == "__main__":
    unittest.main()
