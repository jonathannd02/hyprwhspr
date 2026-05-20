import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from mic_osd.visualizations.base import StateManager, VisualizerState
from mic_osd.visualizations.waveform import WaveformVisualization


class MicOSDWaveformTests(unittest.TestCase):
    def test_starting_state_is_parsed(self):
        manager = StateManager()
        manager.set_state_from_string("starting")
        self.assertEqual(manager.current_state, VisualizerState.STARTING)
        self.assertGreater(manager.get_animation_value(), 0.0)

    def test_level_only_update_moves_bars(self):
        viz = WaveformVisualization()
        self.assertEqual(float(viz.bar_heights.max()), 0.0)

        viz.update(0.5, samples=None)

        self.assertGreater(float(viz.bar_heights.max()), 0.0)
        self.assertGreater(float(viz.bar_heights.mean()), 0.0)

    def test_silence_decays_level_only_bars(self):
        viz = WaveformVisualization()
        viz.update(0.8, samples=None)
        first_peak = float(viz.bar_heights.max())

        viz.update(0.0, samples=None)

        self.assertLess(float(viz.bar_heights.max()), first_peak)


if __name__ == "__main__":
    unittest.main()
