import threading
import time
import unittest
from unittest import mock

from lib import main


class DummyMicOSDRunner:
    def __init__(self):
        self.hidden = 0
        self.cleared = 0
        self.shown_states = []
        self.set_states = []

    def is_available(self):
        return True

    def show(self, state='recording'):
        self.shown_states.append(state)

    def hide(self):
        self.hidden += 1

    def clear_state(self):
        self.cleared += 1

    def set_state(self, state):
        self.set_states.append(state)


def make_app(runner):
    app = main.hyprwhsprApp.__new__(main.hyprwhsprApp)
    app._cancel_pending_hide = False
    app._cancel_pending_hide_lock = threading.Lock()
    app._mic_osd_hide_generation = 0
    app._mic_osd_runner = runner
    return app


class MicOSDShowHideGenerationTests(unittest.TestCase):
    def test_new_show_cancels_pending_result_hide(self):
        runner = DummyMicOSDRunner()
        app = make_app(runner)
        sleep_entered = threading.Event()
        release_sleep = threading.Event()
        real_sleep = time.sleep

        def fake_sleep(_seconds):
            sleep_entered.set()
            release_sleep.wait(timeout=1)

        with mock.patch.object(main.time, 'sleep', side_effect=fake_sleep):
            app._show_result_and_hide(False)
            self.assertTrue(sleep_entered.wait(timeout=1))

            app._show_mic_osd(state='starting')
            release_sleep.set()

            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and runner.hidden == 0:
                real_sleep(0.01)

        self.assertEqual(runner.hidden, 0)
        self.assertEqual(runner.cleared, 0)
        self.assertEqual(runner.shown_states, ['starting'])
        self.assertEqual(runner.set_states, ['error'])

    def test_result_hide_still_hides_without_new_show(self):
        runner = DummyMicOSDRunner()
        app = make_app(runner)
        sleep_entered = threading.Event()
        release_sleep = threading.Event()
        real_sleep = time.sleep

        def fake_sleep(_seconds):
            sleep_entered.set()
            release_sleep.wait(timeout=1)

        with mock.patch.object(main.time, 'sleep', side_effect=fake_sleep):
            app._show_result_and_hide(True)
            self.assertTrue(sleep_entered.wait(timeout=1))
            release_sleep.set()

            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and runner.hidden == 0:
                real_sleep(0.01)

        self.assertEqual(runner.hidden, 1)
        self.assertEqual(runner.cleared, 1)
        self.assertEqual(runner.set_states, ['success'])


if __name__ == '__main__':
    unittest.main()
