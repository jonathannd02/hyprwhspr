# HyperWhisper Visual OSD Design

## Goal

Make the HyperWhisper visual window reliable and context-aware during dictation:

- The visualizer appears immediately when recording is requested.
- The visualizer shows movement while the recorder is receiving audio.
- The visualizer appears above the text cursor when that position is available.
- If text cursor positioning is unavailable, the visualizer falls back to the existing fixed top-left corner.

## Current Behavior

The current mic OSD is a GTK4 layer-shell daemon controlled by `MicOSDRunner`.
It is shown and hidden with `SIGUSR1` and `SIGUSR2`, while visual state is passed through `~/.config/hyprwhspr/visualizer_state`.

The OSD currently opens its own `sounddevice.InputStream` in `lib/mic_osd/audio.py` to draw the waveform. The main app already owns a separate recorder stream through `AudioCapture`. When the OSD cannot open or read from a second input stream, the window may still appear but the waveform stays flat.

The app also writes scaled recorder levels to `~/.config/hyprwhspr/audio_level` every 100 ms, but the OSD does not use that file for rendering.

The OSD position is currently fixed through layer-shell top-left anchoring and static margins.

## Desired UX

When the user presses the recording shortcut:

1. The OSD appears immediately in a `starting` state.
2. Once recorder callbacks arrive, the OSD switches to `recording`.
3. During recording, waveform bars animate from the main recorder's audio levels.
4. When transcription starts, the OSD switches to `processing`.
5. On success or error, the OSD briefly shows the corresponding state and then hides.

The window position should be:

1. Above the focused text cursor when caret bounds are available.
2. The current fixed top-left corner when caret bounds are unavailable, stale, off-screen, or unsafe to use.

The fallback is intentionally the current fixed position, not focused-window placement.

## Non-Goals

- No full visual redesign.
- No per-app positioning rules in the first implementation.
- No compositor-specific hacks beyond the existing Niri/Wayland environment checks.
- No change to transcription, paste, or text-injection behavior.
- No new user-facing configuration unless implementation reveals a hard need.

## Architecture

### Recorder-Driven Audio Levels

The main recorder remains the single source of truth for microphone audio.
`AudioCapture` already receives audio chunks and updates `current_level`.
The app should write enough visualization data for the OSD without requiring the OSD to open a second microphone stream.

The first implementation should reuse the existing `AUDIO_LEVEL_FILE` IPC and make the OSD synthesize waveform samples from the level history. This avoids broad changes to the recording path and removes the second-stream failure mode.

If later visual fidelity needs to improve, a richer IPC file or Unix socket can carry per-bar RMS levels. That is out of scope for the first fix.

### Visualizer States

Add a `starting` state to the visualizer state model.

Expected states:

- `starting`: OSD is visible, recorder stream has been requested, callbacks are not confirmed yet.
- `recording`: recorder callbacks are arriving and audio levels are available.
- `paused`: long-form recording is paused.
- `processing`: audio capture has stopped and transcription is running.
- `error`: capture or transcription failed.
- `success`: transcription succeeded and text was injected or delivered.

The `starting` state should render a visible indicator and a subtle baseline animation so the user gets immediate feedback even before levels arrive.

### Show Timing

For normal toggle/push-to-talk/continuous recording, the main app should call `_show_mic_osd()` before or immediately after marking recording intent, before stream verification waits complete.

If stream start or verification fails, the app should set `error` and schedule the same short hide behavior used for other errors.

Long-form mode already shows OSD immediately after audio capture starts. It can keep that timing initially, but should still benefit from recorder-driven levels and positioning.

### Positioning

Add a small positioning module for OSD placement decisions.

Responsibilities:

- Query focused caret bounds through AT-SPI when available.
- Validate coordinates against screen bounds and OSD dimensions.
- Convert caret bounds into a top-left OSD target position with padding above the caret.
- Return `None` when caret bounds are unavailable or unsafe.

The OSD window should support dynamic margins before showing. If a caret position exists, the layer-shell window remains top-left anchored but margins are set to the computed target coordinates. If no caret position exists, margins remain the current fixed values.

AT-SPI is already used in `TextInjector` as a fallback for focused app detection. The new caret query should share the same safety assumptions:

- Probe with timeouts.
- Serialize AT-SPI access behind a lock.
- Treat failures as normal fallback, not fatal errors.

### IPC Shape

Keep IPC file-based for this feature:

- `visualizer_state`: state string.
- `audio_level`: current scaled level, already written by the main app.

The OSD should poll `audio_level` while visible. If the file is missing or stale, it should decay bars instead of opening its own stream.

This preserves the daemon signal model and avoids adding a new socket protocol for the first iteration.

## Error Handling

- If the OSD daemon cannot start, recording must still work.
- If AT-SPI is unavailable, positioning falls back to the fixed corner.
- If caret coordinates are off-screen, negative, or too close to screen edges, positioning falls back to the fixed corner or clamps safely.
- If `audio_level` is missing during recording, bars decay and the state indicator remains visible.
- If stream verification fails after the OSD was shown, show `error` briefly and hide.

## Testing

Tests should cover deterministic logic and avoid requiring a live Wayland compositor where possible.

Recommended coverage:

- Position conversion from caret rectangle to OSD margins.
- Rejection of invalid caret rectangles.
- Fixed-position fallback when no caret is available.
- Waveform update from level-only input.
- `starting` state parsing and animation behavior.
- Main app call ordering around initial OSD show can be covered with a small helper function or targeted unit test if extraction is practical.

Manual verification remains necessary for:

- OSD appears immediately after F1.
- OSD animates while speaking.
- OSD appears above a supported text cursor.
- OSD falls back to fixed corner in unsupported apps.
- Error state appears briefly when the microphone cannot start.

## Implementation Boundary

Likely files:

- `lib/mic_osd/visualizations/base.py`: add `STARTING`.
- `lib/mic_osd/visualizations/waveform.py`: support level-only waveform updates and `starting`.
- `lib/mic_osd/main.py`: poll `audio_level`, stop using a second mic stream for normal daemon visualization.
- `lib/mic_osd/window.py`: support dynamic layer-shell margins.
- `lib/mic_osd/positioning.py`: new deterministic positioning helpers and AT-SPI caret query.
- `lib/mic_osd/runner.py`: optionally trigger position refresh before show.
- `lib/main.py`: show OSD immediately in `starting`, switch to `recording` after stream verification, error-hide on startup failure.

The implementation plan should keep changes incremental and testable.
