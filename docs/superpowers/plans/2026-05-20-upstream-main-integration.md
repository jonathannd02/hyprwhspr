# Upstream Main Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Merge the current `upstream/main` updates into `personal/main` while preserving the user's local hyprwhspr behavior.

**Architecture:** Treat `upstream/main` as the source of public release changes and `personal/main` as the user's stable local distribution. Merge upstream into an isolated update branch, then reconcile overlapping Niri/text-injection changes by keeping one clear implementation path and preserving local personal features.

**Tech Stack:** Git, Python 3, shell wrapper validation, hyprwhspr CLI/runtime modules.

---

### Task 1: Integrate Upstream Main Into Personal Branch

**Files:**
- Modify via merge: `.github/workflows/continue-pr-review.yml`
- Modify via merge: `README.md`
- Modify via merge: `website/package-lock.json`
- Modify: `docs/CONFIGURATION.md`
- Modify: `lib/src/cli_commands.py`
- Modify: `lib/src/text_injector.py`
- Preserve local personal files/features: `lib/src/config_manager.py`, `lib/src/paths.py`, `lib/src/whisper_manager.py`, `lib/src/realtime_client.py`, `lib/main.py`, `lib/cli.py`, `bin/hyprwhspr`, `share/config.schema.json`, local audio assets, local docs under `docs/superpowers/`

- [x] **Step 1: Record the starting commit**

Run:

```bash
git rev-parse HEAD
```

Expected: a commit on `update/upstream-main-20260520` descended from `personal/main`.

- [x] **Step 2: Merge upstream/main**

Run:

```bash
git merge upstream/main --no-edit
```

Expected: merge succeeds or produces conflicts to resolve. If conflicts happen, resolve them in favor of preserving local personal features while adding upstream Niri/setup validation behavior.

- [x] **Step 3: Reconcile Niri focused-window detection**

Edit `lib/src/text_injector.py` so `_get_active_window_info()` has a single Niri path before Hyprland. It should:

```python
        # Niri
        if shutil.which('niri'):
            try:
                result = subprocess.run(
                    ['niri', 'msg', '--json', 'focused-window'],
                    capture_output=True, text=True, timeout=0.5
                )
                if result.returncode == 0 and result.stdout.strip():
                    window = json.loads(result.stdout)
                    app_id = (window.get('app_id') or '').strip()
                    if app_id:
                        return {
                            'class': app_id,
                            'title': window.get('title', ''),
                            'pid': window.get('pid'),
                            'source': 'niri',
                        }
            except Exception:
                pass
```

Expected: no duplicate second Niri block remains later in `_get_active_window_info()`.

- [x] **Step 4: Keep improved terminal detection**

In `lib/src/text_injector.py`, keep upstream's desktop/app-id normalization in `_is_terminal()`:

```python
        window_class = window_info.get('class', '').lower()
        window_identifiers = {window_class}
        if window_class.endswith('.desktop'):
            window_identifiers.add(window_class[:-len('.desktop')])
        if '.' in window_class:
            window_identifiers.add(window_class.rsplit('.', 1)[-1])
```

Expected: terminal detection includes `org.alacritty.alacritty` and returns `bool(window_identifiers & terminals)`.

- [x] **Step 5: Preserve local text preprocessing and paste timing**

Verify `lib/src/text_injector.py` still:

```python
if self.config_manager and hasattr(self.config_manager, 'refresh_word_learning_config'):
    self.config_manager.refresh_word_learning_config()
```

and still applies:

```python
processed = self._filter_banned_words(processed)
```

and still uses configurable paste timing:

```python
trigger_release_delay = self._get_float_setting('paste_trigger_release_delay', 0.35)
clipboard_delay_key = 'paste_kitty_clipboard_sync_delay' if is_terminal else 'paste_clipboard_sync_delay'
```

Expected: local `banned_words`, `word_overrides`, and paste latency tuning remain functional.

- [x] **Step 6: Preserve local CLI features while adding upstream Niri validation**

Verify `lib/src/cli_commands.py` still contains local word-review support:

```python
def words_command(action: str):
```

and still imports `LAST_TRANSCRIPTION_FILE`.

Verify it also includes upstream Niri support:

```python
def _is_niri_session() -> bool:
```

and imports compositor environment variables during systemd setup:

```python
'WAYLAND_DISPLAY', 'XDG_CURRENT_DESKTOP',
'HYPRLAND_INSTANCE_SIGNATURE', 'NIRI_SOCKET',
```

and validates `NIRI_SOCKET` in the systemd user environment when running under Niri.

Expected: local word-review/audio/config behavior is not removed by the upstream merge.

- [x] **Step 7: Verify docs include upstream Niri guidance and local docs remain**

Verify `docs/CONFIGURATION.md` contains the Niri startup guidance:

```kdl
spawn-at-startup "dbus-update-activation-environment" "--systemd" "WAYLAND_DISPLAY" "XDG_CURRENT_DESKTOP" "NIRI_SOCKET"
```

Expected: local personal documentation sections such as `banned_words`, `word_overrides`, paste timing, and audio ducking are still present.

- [x] **Step 8: Run verification**

Run:

```bash
python3 -m compileall -q lib
bash -n bin/hyprwhspr
python3 - <<'PY'
import json
import sys
sys.path.insert(0, 'lib/src')
from text_injector import TextInjector
injector = TextInjector()
info = injector._get_active_window_info()
print(json.dumps(info, sort_keys=True))
print(injector._is_terminal({'class': 'org.alacritty.alacritty'}))
print(injector._is_terminal({'class': 'kitty.desktop'}))
PY
```

Expected: compile and shell syntax pass; Python smoke prints active-window JSON or `null`, then `True`, then `True`.

- [x] **Step 9: Commit the integration**

Run:

```bash
git status --short
git add .
git commit -m "merge upstream main into personal branch"
```

Expected: one integration commit on `update/upstream-main-20260520`.
