# HyperWhisper Visual OSD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the HyperWhisper visualizer appear immediately, animate from the active recorder stream, and position above the text cursor when possible with the current fixed corner as fallback.

**Architecture:** Keep the existing GTK4 layer-shell daemon and signal-based show/hide model. Remove the OSD's dependency on a second microphone stream by polling recorder-owned audio levels, add a deterministic caret-to-position module with AT-SPI as best-effort input, and update the main app's recording start sequence to show `starting` immediately and transition to `recording` after callbacks arrive.

**Tech Stack:** Python 3, GTK4/Gdk/Gtk4LayerShell, AT-SPI via `gi.repository.Atspi`, standard-library `unittest`, existing file IPC under `~/.config/hyprwhspr`.

---

## File Structure

- Create `tests/__init__.py`: allow `python3 -m unittest discover -s tests -v`.
- Create `tests/test_mic_osd_positioning.py`: deterministic tests for caret rectangle validation and OSD coordinate calculation.
- Create `tests/test_mic_osd_level_source.py`: deterministic tests for parsing and staleness handling of `audio_level`.
- Create `tests/test_mic_osd_waveform.py`: deterministic tests for `starting` state parsing and level-only waveform movement.
- Create `lib/mic_osd/positioning.py`: caret rectangle dataclass, coordinate calculation, and best-effort AT-SPI caret query.
- Create `lib/mic_osd/level_source.py`: pure helper for reading fresh scaled audio levels from a file.
- Modify `lib/mic_osd/visualizations/base.py`: add `STARTING` state and animation/color behavior.
- Modify `lib/mic_osd/visualizations/waveform.py`: synthesize bar movement from level-only updates.
- Modify `lib/mic_osd/window.py`: allow dynamic layer-shell margins and expose primary monitor dimensions.
- Modify `lib/mic_osd/main.py`: use file-driven audio levels in daemon mode, apply caret-first positioning before show.
- Modify `lib/mic_osd/runner.py`: accept a show state and set it before signaling the daemon.
- Modify `lib/main.py`: show OSD immediately in `starting`, start level monitoring as soon as capture starts, transition/error states explicitly.

---

### Task 1: Add Deterministic OSD Positioning

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_mic_osd_positioning.py`
- Create: `lib/mic_osd/positioning.py`

- [ ] **Step 1: Write failing positioning tests**

Create `tests/__init__.py` as an empty file.

Create `tests/test_mic_osd_positioning.py` with:

```python
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
```

- [ ] **Step 2: Run the positioning tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_mic_osd_positioning -v
```

Expected: failure with `ModuleNotFoundError: No module named 'mic_osd.positioning'`.

- [ ] **Step 3: Implement positioning helpers**

Create `lib/mic_osd/positioning.py` with:

```python
"""Best-effort positioning helpers for the mic OSD."""

from __future__ import annotations

from dataclasses import dataclass
import math
import threading
from typing import Optional, Tuple


@dataclass(frozen=True)
class CaretRect:
    """Screen-space caret bounds."""

    x: float
    y: float
    width: float
    height: float


_ATSPI_LOCK = threading.Lock()
_ATSPI_MODULE = None
_ATSPI_AVAILABLE = None


def _is_finite_rect(rect: CaretRect) -> bool:
    return all(math.isfinite(value) for value in (rect.x, rect.y, rect.width, rect.height))


def compute_osd_position(
    caret: Optional[CaretRect],
    screen_width: int,
    screen_height: int,
    osd_width: int,
    osd_height: int,
    *,
    fixed_x: int = 10,
    fixed_y: int = 10,
    gap: int = 8,
    margin: int = 10,
) -> Optional[Tuple[int, int]]:
    """Return top-left OSD coordinates above a caret, or None for fixed fallback."""
    if caret is None:
        return None
    if screen_width <= 0 or screen_height <= 0 or osd_width <= 0 or osd_height <= 0:
        return None
    if not _is_finite_rect(caret):
        return None
    if caret.width < 0 or caret.height <= 0:
        return None

    caret_center_x = caret.x + (caret.width / 2)
    if caret_center_x < 0 or caret_center_x > screen_width:
        return None
    if caret.y < 0 or caret.y > screen_height:
        return None

    y = int(round(caret.y - osd_height - gap))
    if y < margin:
        return None

    min_x = max(0, margin)
    max_x = max(min_x, screen_width - osd_width - margin)
    x = int(round(caret_center_x - (osd_width / 2)))
    x = max(min_x, min(max_x, x))

    if x == fixed_x and y == fixed_y:
        return None
    return (x, y)


def _load_atspi(timeout: float = 0.5):
    """Load AT-SPI once, with a timeout so OSD show never blocks for long."""
    global _ATSPI_AVAILABLE, _ATSPI_MODULE

    if _ATSPI_AVAILABLE is not None:
        return _ATSPI_MODULE if _ATSPI_AVAILABLE else None

    result = [None]

    def probe():
        try:
            import gi

            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi

            Atspi.init()
            result[0] = Atspi
        except Exception:
            result[0] = None

    thread = threading.Thread(target=probe, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if result[0] is None:
        _ATSPI_AVAILABLE = False
        _ATSPI_MODULE = None
        return None

    _ATSPI_AVAILABLE = True
    _ATSPI_MODULE = result[0]
    return _ATSPI_MODULE


def _find_focused_text_accessible(Atspi):
    desktop = Atspi.get_desktop(0)
    stack = []
    for i in range(desktop.get_child_count()):
        child = desktop.get_child_at_index(i)
        if child is not None:
            stack.append((child, 0))

    while stack:
        accessible, depth = stack.pop()
        try:
            states = accessible.get_state_set()
            if states and states.contains(Atspi.StateType.FOCUSED):
                text_iface = accessible.get_text_iface()
                if text_iface is not None:
                    return text_iface
        except Exception:
            pass

        if depth >= 8:
            continue

        try:
            child_count = accessible.get_child_count()
        except Exception:
            continue
        for index in range(child_count - 1, -1, -1):
            try:
                child = accessible.get_child_at_index(index)
            except Exception:
                child = None
            if child is not None:
                stack.append((child, depth + 1))

    return None


def get_focused_caret_rect(timeout: float = 0.5) -> Optional[CaretRect]:
    """Return focused caret bounds from AT-SPI, or None when unavailable."""
    if not _ATSPI_LOCK.acquire(timeout=timeout):
        return None
    try:
        Atspi = _load_atspi(timeout=timeout)
        if Atspi is None:
            return None

        text_iface = _find_focused_text_accessible(Atspi)
        if text_iface is None:
            return None

        offset = text_iface.get_caret_offset()
        if offset < 0:
            return None
        rect = text_iface.get_character_extents(offset, Atspi.CoordType.SCREEN)
        return CaretRect(
            x=float(rect.x),
            y=float(rect.y),
            width=float(rect.width),
            height=float(rect.height),
        )
    except Exception:
        return None
    finally:
        _ATSPI_LOCK.release()
```

- [ ] **Step 4: Run positioning tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_mic_osd_positioning -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit positioning helpers**

Run:

```bash
git add tests/__init__.py tests/test_mic_osd_positioning.py lib/mic_osd/positioning.py
git commit -m "feat: add caret osd positioning helpers"
```

Expected: one commit containing only the positioning helper and tests.

---

### Task 2: Add File-Based Audio Level Source

**Files:**
- Create: `tests/test_mic_osd_level_source.py`
- Create: `lib/mic_osd/level_source.py`

- [ ] **Step 1: Write failing level-source tests**

Create `tests/test_mic_osd_level_source.py` with:

```python
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
            stale.touch(times=(old, old))
            self.assertIsNone(read_audio_level(stale, max_age_seconds=1.0))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run level-source tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_mic_osd_level_source -v
```

Expected: failure with `ModuleNotFoundError: No module named 'mic_osd.level_source'`.

- [ ] **Step 3: Implement audio-level file reader**

Create `lib/mic_osd/level_source.py` with:

```python
"""File-based audio level source for the mic OSD."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional


def read_audio_level(path: Path, *, max_age_seconds: float = 1.0) -> Optional[float]:
    """Read a fresh scaled audio level from path, returning None when unavailable."""
    try:
        stat = path.stat()
    except OSError:
        return None

    if max_age_seconds >= 0 and time.time() - stat.st_mtime > max_age_seconds:
        return None

    try:
        value = float(path.read_text().strip())
    except (OSError, ValueError):
        return None

    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value
```

- [ ] **Step 4: Run level-source tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_mic_osd_level_source -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit level-source helper**

Run:

```bash
git add tests/test_mic_osd_level_source.py lib/mic_osd/level_source.py
git commit -m "feat: read recorder audio levels for osd"
```

Expected: one commit containing only the level source helper and tests.

---

### Task 3: Add Starting State and Level-Only Waveform Animation

**Files:**
- Create: `tests/test_mic_osd_waveform.py`
- Modify: `lib/mic_osd/visualizations/base.py`
- Modify: `lib/mic_osd/visualizations/waveform.py`

- [ ] **Step 1: Write failing waveform tests**

Create `tests/test_mic_osd_waveform.py` with:

```python
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
```

- [ ] **Step 2: Run waveform tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_mic_osd_waveform -v
```

Expected: at least `AttributeError: STARTING` or the level-only bars remain at zero.

- [ ] **Step 3: Add `STARTING` to visualizer state management**

In `lib/mic_osd/visualizations/base.py`, change `VisualizerState` to:

```python
class VisualizerState(Enum):
    """States for the visualizer indicator."""
    STARTING = "starting"        # Recording requested, stream not confirmed yet
    RECORDING = "recording"      # Pulsing red dot
    PAUSED = "paused"            # Static amber dot
    PROCESSING = "processing"    # Green wave animation
    ERROR = "error"              # Red flash/strobe
    SUCCESS = "success"          # Green pulse + fade
```

Change `set_state_from_string()` state map to:

```python
        state_map = {
            'starting': VisualizerState.STARTING,
            'recording': VisualizerState.RECORDING,
            'paused': VisualizerState.PAUSED,
            'processing': VisualizerState.PROCESSING,
            'error': VisualizerState.ERROR,
            'success': VisualizerState.SUCCESS,
        }
```

Change `get_state_color()` color map to:

```python
        color_map = {
            VisualizerState.STARTING: theme.processing_dot,
            VisualizerState.RECORDING: theme.recording_dot,
            VisualizerState.PAUSED: theme.paused_dot,
            VisualizerState.PROCESSING: theme.processing_dot,
            VisualizerState.ERROR: theme.error_dot,
            VisualizerState.SUCCESS: theme.success_dot,
        }
```

Add this branch near the top of `get_animation_value()`:

```python
        if self.current_state == VisualizerState.STARTING:
            return 0.55 + 0.25 * math.sin(self.animation_phase)
```

Update `is_animating()` so `STARTING` animates continuously by leaving it out of the paused/success stop conditions.

- [ ] **Step 4: Add level-only bar synthesis**

In `lib/mic_osd/visualizations/waveform.py`, add a phase field in `__init__()` after `self.rise_rate`:

```python
        self.level_phase = 0.0
```

Add this helper method before `update()`:

```python
    def _apply_bar_heights(self, new_heights: np.ndarray):
        """Smooth new normalized bar heights into the current bar state."""
        for i in range(self.num_bars):
            if new_heights[i] > self.bar_heights[i]:
                self.bar_heights[i] = (
                    self.rise_rate * new_heights[i] +
                    (1 - self.rise_rate) * self.bar_heights[i]
                )
            else:
                self.bar_heights[i] *= self.decay_rate
                if self.bar_heights[i] < new_heights[i]:
                    self.bar_heights[i] = new_heights[i]

    def _update_from_level(self, level: float):
        """Create visible waveform motion from a recorder-owned scalar level."""
        if level <= 0.001:
            self.bar_heights *= self.decay_rate
            return

        self.level_phase += 0.35
        new_heights = np.zeros(self.num_bars)
        scaled_level = min(1.0, max(0.0, level) * 1.35)
        for i in range(self.num_bars):
            wave = 0.55 + 0.45 * math.sin(self.level_phase + i * 0.72)
            texture = 0.85 + 0.15 * math.sin(self.level_phase * 0.37 + i * 1.91)
            new_heights[i] = min(1.0, max(0.04, scaled_level * wave * texture))
        self._apply_bar_heights(new_heights)
```

In `update()`, replace the duplicated smoothing loop with `_apply_bar_heights(new_heights)`, and change the `else` branch from pure decay to:

```python
        elif level > 0.001:
            self._update_from_level(level)
        else:
            self.bar_heights *= self.decay_rate
```

In `draw()`, treat `STARTING` as a synthetic wave state by adding:

```python
        is_starting = self.state_manager.current_state == VisualizerState.STARTING
```

and changing the processing branch condition from:

```python
            if is_processing:
```

to:

```python
            if is_processing or is_starting:
```

Inside that branch, use a lower baseline for `starting`:

```python
                base_height_boost = 0.7 if is_processing else 0.18
```

- [ ] **Step 5: Run waveform tests and verify they pass**

Run:

```bash
python3 -m unittest tests.test_mic_osd_waveform -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit waveform state changes**

Run:

```bash
git add tests/test_mic_osd_waveform.py lib/mic_osd/visualizations/base.py lib/mic_osd/visualizations/waveform.py
git commit -m "feat: animate osd from recorder levels"
```

Expected: one commit containing only waveform/state changes and tests.

---

### Task 4: Wire Level Source and Caret Positioning Into the OSD Daemon

**Files:**
- Modify: `lib/mic_osd/window.py`
- Modify: `lib/mic_osd/main.py`

- [ ] **Step 1: Add dynamic position methods to `OSDWindow`**

In `lib/mic_osd/window.py`, add these fields in `__init__()` before `_setup_layer_shell()`:

```python
        self._fixed_top = 10
        self._fixed_left = 10
```

In `_setup_layer_shell()`, replace the hard-coded margins:

```python
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.TOP, 10)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.LEFT, 10)
```

with:

```python
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.TOP, self._fixed_top)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.LEFT, self._fixed_left)
```

Add these methods to `OSDWindow`:

```python
    def set_layer_position(self, x: int | None, y: int | None):
        """Move the layer-shell surface, or reset to fixed fallback when None."""
        if not LAYER_SHELL_AVAILABLE:
            return

        left = self._fixed_left if x is None else max(0, int(x))
        top = self._fixed_top if y is None else max(0, int(y))
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.LEFT, left)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.TOP, top)

    def reset_layer_position(self):
        """Return the OSD to its fixed fallback position."""
        self.set_layer_position(None, None)

    def get_primary_monitor_size(self):
        """Return primary monitor size for position validation."""
        display = Gdk.Display.get_default()
        if display is None:
            return (0, 0)
        monitors = display.get_monitors()
        monitor = monitors.get_item(0) if monitors is not None and monitors.get_n_items() > 0 else None
        if monitor is None:
            return (0, 0)
        geometry = monitor.get_geometry()
        return (geometry.width, geometry.height)
```

- [ ] **Step 2: Make daemon mode file-level driven**

In `lib/mic_osd/main.py`, update the path imports to include `AUDIO_LEVEL_FILE`:

```python
    from ..src.paths import RECORDING_STATUS_FILE, VISUALIZER_STATE_FILE, AUDIO_LEVEL_FILE
```

and in both fallback import branches define:

```python
        AUDIO_LEVEL_FILE = xdg_config / 'hyprwhspr' / 'audio_level'
```

Add imports near existing mic OSD imports:

```python
from .level_source import read_audio_level
from .positioning import compute_osd_position, get_focused_caret_rect
```

In `MicOSD.__init__()`, add:

```python
        self._use_file_audio = daemon
```

In `_show()`, before `self.window.set_visible(True)`, add:

```python
        self._apply_position()
```

Change the audio-monitor startup block in `_show()` from unconditional to:

```python
        if not self._use_file_audio:
            if not self.audio_monitor:
                self.audio_monitor = AudioMonitor(samplerate=44100, blocksize=1024)

            try:
                self.audio_monitor.start()
            except RuntimeError as e:
                print(f"[MIC-OSD] Audio monitoring unavailable, showing without waveform: {e}", flush=True)
                self.audio_monitor = None
```

Add this method to `MicOSD` before `_update()`:

```python
    def _apply_position(self):
        """Position above focused caret when available, otherwise reset to fixed fallback."""
        if not self.window:
            return

        try:
            screen_width, screen_height = self.window.get_primary_monitor_size()
            caret = get_focused_caret_rect()
            position = compute_osd_position(
                caret,
                screen_width=screen_width,
                screen_height=screen_height,
                osd_width=self.width,
                osd_height=self.height,
            )
            if position is None:
                self.window.reset_layer_position()
            else:
                self.window.set_layer_position(*position)
        except Exception as e:
            print(f"[MIC-OSD] Positioning fallback: {e}", flush=True)
            try:
                self.window.reset_layer_position()
            except Exception:
                pass
```

Replace `_update()` with:

```python
    def _update(self):
        """Update visualization with current audio data."""
        if not self.window or not self.visible:
            return True

        if self._use_file_audio:
            level = read_audio_level(AUDIO_LEVEL_FILE, max_age_seconds=1.0)
            self.window.update(0.0 if level is None else level, None)
            return True

        if self.audio_monitor:
            level = self.audio_monitor.get_level()
            samples = self.audio_monitor.get_samples()
            self.window.update(level, samples)

        return True
```

In `_hide()`, before hiding the window, add:

```python
            self.window.reset_layer_position()
```

- [ ] **Step 3: Compile OSD modules**

Run:

```bash
python3 -m py_compile lib/mic_osd/window.py lib/mic_osd/main.py lib/mic_osd/level_source.py lib/mic_osd/positioning.py
```

Expected: command exits with no output.

- [ ] **Step 4: Run focused unit tests**

Run:

```bash
python3 -m unittest tests.test_mic_osd_positioning tests.test_mic_osd_level_source tests.test_mic_osd_waveform -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit OSD daemon integration**

Run:

```bash
git add lib/mic_osd/window.py lib/mic_osd/main.py
git commit -m "feat: drive osd daemon from recorder state"
```

Expected: one commit containing only OSD daemon integration changes.

---

### Task 5: Show OSD Immediately From the Recording Pipeline

**Files:**
- Modify: `lib/mic_osd/runner.py`
- Modify: `lib/main.py`

- [ ] **Step 1: Let the runner show a requested state**

In `lib/mic_osd/runner.py`, change the signature of `show()` from:

```python
    def show(self) -> bool:
```

to:

```python
    def show(self, state: str = "recording") -> bool:
```

At the start of the method after availability/daemon checks pass and before sending `SIGUSR1`, add:

```python
            self.set_state(state)
```

The resulting signal block should be:

```python
        try:
            self.set_state(state)
            pid = self._orphaned_daemon_pid if self._orphaned_daemon_pid is not None else self._process.pid
            os.kill(pid, signal.SIGUSR1)
            return True
```

- [ ] **Step 2: Add state parameter to `_show_mic_osd()`**

In `lib/main.py`, replace `_show_mic_osd()` with:

```python
    def _show_mic_osd(self, state: str = 'recording'):
        """Show mic-osd visualization overlay."""
        with self._cancel_pending_hide_lock:
            self._cancel_pending_hide = True
        if self._mic_osd_runner and self._mic_osd_runner.is_available():
            self._mic_osd_runner.show(state=state)
```

- [ ] **Step 3: Show `starting` immediately in `_start_recording()`**

In `lib/main.py`, in `_start_recording()`, immediately after:

```python
        print("Recording started", flush=True)
```

add:

```python
        self._show_mic_osd(state='starting')
```

- [ ] **Step 4: Start level monitoring as soon as capture starts**

In `_start_recording()`, after:

```python
                if not self.audio_capture.start_recording(streaming_callback=streaming_callback):
                    raise RuntimeError("start_recording() returned False")
```

add:

```python
                self._start_audio_level_monitoring()
```

Remove the duplicate monitoring block that currently appears after stream stability is confirmed:

```python
                # Stream is working and stable - start monitoring
                self._start_audio_level_monitoring()
```

- [ ] **Step 5: Transition to recording instead of showing late**

In `_start_recording()`, replace:

```python
                # Stream is verified working - show mic-osd visualization
                self._show_mic_osd()
```

with:

```python
                # Stream is verified working - switch visualizer from starting to recording
                self._show_mic_osd(state='recording')
```

- [ ] **Step 6: Show error state on stream startup failures**

In the `verify_and_play_sound()` failure path, replace:

```python
                    # Hide mic-osd visualization
                    self._hide_mic_osd()
```

with:

```python
                    self._stop_audio_level_monitoring()
                    self._show_result_and_hide(False)
```

In the `verify_stream_stable()` failure path, replace:

```python
                    # Hide mic-osd visualization
                    self._hide_mic_osd()
```

with:

```python
                    self._stop_audio_level_monitoring()
                    self._show_result_and_hide(False)
```

In the `except (RuntimeError, Exception) as e:` recording-start failure block, replace:

```python
                # Clean up resources
                self._hide_mic_osd()
                self._stop_audio_level_monitoring()
```

with:

```python
                # Clean up resources and briefly show the startup error state
                self._stop_audio_level_monitoring()
                self._show_result_and_hide(False)
```

In the outer `except Exception as e:` block, replace the same hide/stop pair with the same stop/error-hide sequence.

- [ ] **Step 7: Compile main app and runner**

Run:

```bash
python3 -m py_compile lib/main.py lib/mic_osd/runner.py
```

Expected: command exits with no output.

- [ ] **Step 8: Run focused unit tests**

Run:

```bash
python3 -m unittest tests.test_mic_osd_positioning tests.test_mic_osd_level_source tests.test_mic_osd_waveform -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit recording pipeline integration**

Run:

```bash
git add lib/main.py lib/mic_osd/runner.py
git commit -m "feat: show osd immediately during recording startup"
```

Expected: one commit containing only runner and main recording start changes.

---

### Task 6: Full Verification

**Files:**
- Verify all files changed by Tasks 1-5.

- [ ] **Step 1: Run Python unit tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Compile the Python package**

Run:

```bash
python3 -m compileall -q lib
```

Expected: command exits with no output.

- [ ] **Step 3: Check shell wrapper syntax**

Run:

```bash
bash -n bin/hyprwhspr
```

Expected: command exits with no output.

- [ ] **Step 4: Smoke-test AT-SPI caret fallback safely**

Run:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, 'lib')
from mic_osd.positioning import get_focused_caret_rect, compute_osd_position

caret = get_focused_caret_rect(timeout=0.5)
print(caret)
print(compute_osd_position(caret, 1920, 1080, 200, 40))
PY
```

Expected: prints either `None` and `None`, or a `CaretRect(...)` plus coordinate tuple. It must not hang or raise.

- [ ] **Step 5: Manual OSD verification on the local session**

Restart the user service:

```bash
systemctl --user restart hyprwhspr.service
journalctl --user -u hyprwhspr.service -n 60 --no-pager
```

Expected: service starts and logs `[INIT] Mic-OSD daemon started` or a clear OSD dependency warning while recording still works.

Manually verify:

- Press F1 in Codex or another text input.
- Expected: OSD appears immediately in `starting`.
- Speak for two seconds.
- Expected: waveform bars move while speaking.
- Stop recording.
- Expected: OSD switches to `processing`, then `success` or `error`, then hides.
- Repeat in an app where caret coordinates are unavailable.
- Expected: OSD appears in the fixed top-left fallback.

- [ ] **Step 6: Commit any final fixes**

If verification required fixes, run:

```bash
git status --short
git add lib/main.py lib/mic_osd/main.py lib/mic_osd/window.py lib/mic_osd/runner.py lib/mic_osd/level_source.py lib/mic_osd/positioning.py lib/mic_osd/visualizations/base.py lib/mic_osd/visualizations/waveform.py tests
git commit -m "fix: stabilize visual osd verification"
```

Expected: no commit is needed if Tasks 1-5 already pass; otherwise one focused fix commit is created.

- [ ] **Step 7: Final status check**

Run:

```bash
git status --short --branch
git log --oneline -6
```

Expected: branch is `codex/hyperwhisper-visual-osd`, working tree is clean apart from ignored cache files, and recent commits correspond to this plan.
