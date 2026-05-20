import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from lib import main


class FakeConfig:
    def get_setting(self, key, default=None):
        return default


class FakeAudioCapture:
    current_level = 0.001

    def __init__(self):
        self.started = 0
        self.paused = 0

    def start_recording(self):
        self.started += 1
        return True

    def pause_recording(self):
        self.paused += 1
        return [1, 2, 3]

    def get_audio_level(self):
        return 0.42


class FakeAudioManager:
    def play_start_sound(self):
        pass

    def play_stop_sound(self):
        pass


class FakeSegmentManager:
    def __init__(self):
        self.started = False
        self.saved = []

    def start_session(self):
        self.started = True

    def save_segment(self, audio_data):
        self.saved.append(audio_data)


def make_app():
    app = main.hyprwhsprApp.__new__(main.hyprwhsprApp)
    app.config = FakeConfig()
    app.audio_capture = FakeAudioCapture()
    app.audio_manager = FakeAudioManager()
    app._longform_segment_manager = FakeSegmentManager()
    app._longform_state = "IDLE"
    app._longform_language_override = None
    app._audio_level_stop = threading.Event()
    app.audio_level_thread = None
    app._visualizer_states = []
    app._shown_osd_states = []
    app._auto_save_starts = 0
    app._auto_save_stops = 0
    app.muted_cancelled = False

    app._write_longform_state = lambda state: None
    app._set_visualizer_state = app._visualizer_states.append
    app._show_mic_osd = lambda state="recording": app._shown_osd_states.append(state)
    app._start_longform_auto_save_timer = lambda: setattr(
        app, "_auto_save_starts", app._auto_save_starts + 1
    )
    app._stop_longform_auto_save_timer = lambda: setattr(
        app, "_auto_save_stops", app._auto_save_stops + 1
    )
    app._cancel_recording_muted = lambda: setattr(app, "muted_cancelled", True)
    return app


class LongformAudioLevelTests(unittest.TestCase):
    def wait_for_file(self, path: Path):
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if path.exists():
                return True
            time.sleep(0.01)
        return False

    def test_longform_start_writes_levels_and_pause_removes_them(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            level_file = Path(tmpdir) / "audio_level"
            app = make_app()

            with mock.patch.object(main, "AUDIO_LEVEL_FILE", level_file):
                app._longform_start_recording()

                self.assertTrue(self.wait_for_file(level_file))
                self.assertEqual(level_file.read_text(), "0.420")
                self.assertFalse(app.muted_cancelled)

                app._longform_pause_recording()

                self.assertEqual(app._longform_state, "PAUSED")
                self.assertFalse(level_file.exists())
                self.assertIsNone(app.audio_level_thread)


if __name__ == "__main__":
    unittest.main()
