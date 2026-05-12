# Self-Editing Workflow Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build F1-toggle self-editing dictation plus Niri-aware app profiles so hyprwhspr edits the current dictation buffer before paste and then uses the safest paste behavior for the focused app.

**Architecture:** Add three small, testable modules under `lib/src`: one for deterministic self-edit parsing, one for workflow profile resolution, and one for last-transcription payload building. Keep integration thin: `lib/main.py` applies self-editing only in the normal F1-toggle recording path, while `lib/src/text_injector.py` resolves app profile and paste policy at injection time.

**Tech Stack:** Python 3, standard-library `unittest`, existing hyprwhspr modules, Niri focused-window metadata, Wayland paste tools (`wtype`/`ydotool`).

---

## File Structure

- Create `tests/__init__.py`: marks tests as a package.
- Create `tests/test_self_editing.py`: deterministic tests for inline edit grammar.
- Create `tests/test_workflow_profiles.py`: tests app/profile/paste-policy resolution.
- Create `tests/test_transcription_state.py`: tests `last_transcription.json` payload shape and backward-compatible review text.
- Create `tests/test_recording_pipeline.py`: tests F1-toggle-only self-edit pipeline without importing `lib/main.py`.
- Create `lib/src/self_editing.py`: `SelfEditParser`, edit result dataclasses, safe deterministic buffer editing.
- Create `lib/src/workflow_profiles.py`: focused-window context normalization, profile resolver, paste policy.
- Create `lib/src/transcription_state.py`: payload builder for last-transcription state and review-text selection.
- Create `lib/src/dictation_pipeline.py`: tiny orchestration for F1-toggle raw transcript to self-edit result.
- Modify `lib/src/text_injector.py`: resolve workflow profile from focused window, apply paste policy, return injection metadata.
- Modify `lib/main.py`: apply self-editing only in `_process_audio`, write extended last-transcription state after injection attempt.
- Modify `lib/src/cli_commands.py`: make `words review` read `processed_text`, `final_text`, or legacy `text`.

## Task 1: Add Failing Self-Edit Parser Tests

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_self_editing.py`

- [ ] **Step 1: Create the tests package marker**

Create `tests/__init__.py` with exactly:

```python
"""Tests for hyprwhspr local workflow features."""
```

- [ ] **Step 2: Write failing parser tests**

Create `tests/test_self_editing.py` with exactly:

```python
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "lib" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from self_editing import SelfEditParser


class SelfEditParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = SelfEditParser()

    def parse(self, text):
        return self.parser.parse(text)

    def test_delete_everything_clears_buffer(self):
        result = self.parse("Maak een lang plan. Delete alles wat ik net gezegd heb")

        self.assertEqual(result.final_text, "")
        self.assertEqual(len(result.edits), 1)
        self.assertEqual(result.edits[0].command, "clear_buffer")
        self.assertTrue(result.edits[0].applied)

    def test_verwijder_laatste_zin_removes_only_last_sentence(self):
        result = self.parse("Eerste zin. Tweede zin. Verwijder de laatste zin")

        self.assertEqual(result.final_text, "Eerste zin.")
        self.assertEqual(result.edits[0].command, "remove_last_sentence")

    def test_verwijder_laatste_woord_removes_one_word(self):
        result = self.parse("Open het bestand verkeerd verwijder het laatste woord")

        self.assertEqual(result.final_text, "Open het bestand")
        self.assertEqual(result.edits[0].command, "remove_last_word")

    def test_corrigeer_oud_naar_nieuw_replaces_latest_match(self):
        result = self.parse(
            "Start de service opnieuw. Corrigeer start de service opnieuw naar systemctl --user restart hyprwhspr."
        )

        self.assertEqual(result.final_text, "systemctl --user restart hyprwhspr.")
        self.assertEqual(result.edits[0].old, "start de service opnieuw")
        self.assertEqual(result.edits[0].new, "systemctl --user restart hyprwhspr")

    def test_in_plaats_van_replaces_latest_match(self):
        result = self.parse("Open test.py. Open main.py in plaats van Open test.py.")

        self.assertEqual(result.final_text, "Open main.py.")
        self.assertEqual(result.edits[0].command, "replace_instead_of")

    def test_nee_wacht_replaces_previous_sentence_with_new_text(self):
        result = self.parse("Maak een bestand test punt py nee wacht maak een bestand main punt py")

        self.assertEqual(result.final_text, "maak een bestand main.py")
        self.assertEqual(result.edits[0].command, "nee_wacht")

    def test_missing_replacement_target_is_ignored_without_erasing_text(self):
        result = self.parse("Open main.py. Corrigeer database naar cache.")

        self.assertEqual(result.final_text, "Open main.py.")
        self.assertEqual(len(result.edits), 0)
        self.assertEqual(len(result.ignored_edits), 1)
        self.assertFalse(result.ignored_edits[0].applied)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the parser tests and verify they fail because the module does not exist**

Run:

```bash
python -m unittest tests.test_self_editing -v
```

Expected: failure with `ModuleNotFoundError: No module named 'self_editing'`.

## Task 2: Implement Self-Edit Parser

**Files:**
- Create: `lib/src/self_editing.py`
- Test: `tests/test_self_editing.py`

- [ ] **Step 1: Add the parser implementation**

Create `lib/src/self_editing.py` with exactly:

```python
"""Deterministic inline self-editing for a single dictation buffer."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class SelfEdit:
    command: str
    phrase: str
    applied: bool
    old: Optional[str] = None
    new: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class SelfEditResult:
    raw_text: str
    final_text: str
    edits: List[SelfEdit] = field(default_factory=list)
    ignored_edits: List[SelfEdit] = field(default_factory=list)


class SelfEditParser:
    """Parse safe correction commands inside one not-yet-pasted dictation."""

    _CLEAR_PATTERNS = (
        "delete alles wat ik net gezegd heb",
        "verwijder alles wat ik net gezegd heb",
    )
    _REMOVE_LAST_SENTENCE = "verwijder de laatste zin"
    _REMOVE_LAST_WORD = "verwijder het laatste woord"
    _NEE_WACHT = "nee wacht"

    def parse(self, text: str) -> SelfEditResult:
        raw_text = text or ""
        working = self._normalize_symbols(self._normalize_spaces(raw_text))
        edits: List[SelfEdit] = []
        ignored: List[SelfEdit] = []

        working, nee_edits = self._apply_nee_wacht(working)
        edits.extend(nee_edits)

        working, clear_edits = self._apply_clear_buffer(working)
        edits.extend(clear_edits)
        if clear_edits and not working:
            return SelfEditResult(raw_text=raw_text, final_text="", edits=edits, ignored_edits=ignored)

        working, sentence_edits = self._apply_remove_last_sentence(working)
        edits.extend(sentence_edits)

        working, word_edits = self._apply_remove_last_word(working)
        edits.extend(word_edits)

        working, replacement_edits, replacement_ignored = self._apply_replacements(working)
        edits.extend(replacement_edits)
        ignored.extend(replacement_ignored)

        return SelfEditResult(
            raw_text=raw_text,
            final_text=self._normalize_spaces(working),
            edits=edits,
            ignored_edits=ignored,
        )

    def _apply_clear_buffer(self, text: str) -> Tuple[str, List[SelfEdit]]:
        lowered = text.lower()
        matches = [(lowered.rfind(pattern), pattern) for pattern in self._CLEAR_PATTERNS]
        index, phrase = max(matches, key=lambda item: item[0])
        if index == -1:
            return text, []
        return "", [SelfEdit(command="clear_buffer", phrase=phrase, applied=True)]

    def _apply_remove_last_sentence(self, text: str) -> Tuple[str, List[SelfEdit]]:
        index = text.lower().rfind(self._REMOVE_LAST_SENTENCE)
        if index == -1:
            return text, []
        before = text[:index].strip()
        return self._remove_last_sentence(before), [
            SelfEdit(command="remove_last_sentence", phrase=self._REMOVE_LAST_SENTENCE, applied=True)
        ]

    def _apply_remove_last_word(self, text: str) -> Tuple[str, List[SelfEdit]]:
        index = text.lower().rfind(self._REMOVE_LAST_WORD)
        if index == -1:
            return text, []
        before = text[:index].strip()
        result = re.sub(r"\s*\S+\s*$", "", before).strip()
        return result, [
            SelfEdit(command="remove_last_word", phrase=self._REMOVE_LAST_WORD, applied=True)
        ]

    def _apply_nee_wacht(self, text: str) -> Tuple[str, List[SelfEdit]]:
        index = text.lower().rfind(self._NEE_WACHT)
        if index == -1:
            return text, []
        before = text[:index].strip()
        after = text[index + len(self._NEE_WACHT):].strip()
        kept = self._remove_last_sentence(before)
        combined = self._join_text(kept, after)
        return combined, [SelfEdit(command="nee_wacht", phrase=self._NEE_WACHT, applied=True, new=after)]

    def _apply_replacements(self, text: str) -> Tuple[str, List[SelfEdit], List[SelfEdit]]:
        edits: List[SelfEdit] = []
        ignored: List[SelfEdit] = []

        text, applied, ignored_edit = self._apply_corrigeer(text)
        if applied:
            edits.append(applied)
        if ignored_edit:
            ignored.append(ignored_edit)

        text, applied, ignored_edit = self._apply_in_plaats_van(text)
        if applied:
            edits.append(applied)
        if ignored_edit:
            ignored.append(ignored_edit)

        return text, edits, ignored

    def _apply_corrigeer(self, text: str) -> Tuple[str, Optional[SelfEdit], Optional[SelfEdit]]:
        match = re.search(
            r"\bcorrigeer\s+(?P<old>.+?)\s+naar\s+(?P<new>.+?)(?P<punct>[.!?])?$",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return text, None, None

        prefix = text[:match.start()].strip()
        old = match.group("old").strip(" .!?")
        new = match.group("new").strip(" .!?")
        punct = match.group("punct") or self._terminal_punctuation(prefix)
        replaced = self._replace_latest(prefix, old, new)
        if replaced is None:
            return prefix, None, SelfEdit(
                command="replace",
                phrase=match.group(0),
                applied=False,
                old=old,
                new=new,
                reason="old text not found",
            )
        return self._ensure_terminal_punctuation(replaced, punct), SelfEdit(
            command="replace",
            phrase=match.group(0),
            applied=True,
            old=old,
            new=new,
        ), None

    def _apply_in_plaats_van(self, text: str) -> Tuple[str, Optional[SelfEdit], Optional[SelfEdit]]:
        marker = " in plaats van "
        index = text.lower().rfind(marker)
        if index == -1:
            return text, None, None

        before_marker = text[:index].strip()
        old_part = text[index + len(marker):].strip()
        punct = self._terminal_punctuation(old_part)
        old = old_part.strip(" .!?")
        base, new = self._split_last_sentence(before_marker)
        new = new.strip(" .!?")
        if not new:
            return base, None, SelfEdit(
                command="replace_instead_of",
                phrase=text[index:].strip(),
                applied=False,
                old=old,
                new=new,
                reason="new text not found",
            )

        replaced = self._replace_latest(base, old, new)
        if replaced is None:
            return base, None, SelfEdit(
                command="replace_instead_of",
                phrase=text[index:].strip(),
                applied=False,
                old=old,
                new=new,
                reason="old text not found",
            )
        return self._ensure_terminal_punctuation(replaced, punct), SelfEdit(
            command="replace_instead_of",
            phrase=text[index:].strip(),
            applied=True,
            old=old,
            new=new,
        ), None

    def _replace_latest(self, text: str, old: str, new: str) -> Optional[str]:
        normalized_text = self._match_normalized(text)
        normalized_old = self._match_normalized(old)
        index = normalized_text.rfind(normalized_old)
        if index == -1:
            return None

        spans = self._normalized_spans(text)
        if index >= len(spans):
            return None
        start = spans[index][0]
        end_norm = index + len(normalized_old) - 1
        if end_norm >= len(spans):
            return None
        end = spans[end_norm][1]
        return text[:start] + new + text[end:]

    def _remove_last_sentence(self, text: str) -> str:
        prefix, _last = self._split_last_sentence(text)
        return prefix

    def _split_last_sentence(self, text: str) -> Tuple[str, str]:
        stripped = text.strip()
        if not stripped:
            return "", ""
        matches = list(re.finditer(r"[.!?]\s+", stripped))
        if not matches:
            return "", stripped
        cut = matches[-1].end()
        return stripped[:cut].strip(), stripped[cut:].strip()

    def _join_text(self, left: str, right: str) -> str:
        if left and right:
            return f"{left} {right}".strip()
        return (left or right).strip()

    def _normalize_spaces(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _normalize_symbols(self, text: str) -> str:
        replacements = {
            " punt ": ".",
            " punt": ".",
            " komma ": ", ",
            " vraagteken": "?",
            " uitroepteken": "!",
        }
        result = f" {text} "
        for spoken, symbol in replacements.items():
            result = result.replace(spoken, symbol)
        return self._normalize_spaces(result)

    def _match_normalized(self, text: str) -> str:
        return "".join(ch.lower() for ch in text if ch.isalnum())

    def _normalized_spans(self, text: str) -> List[Tuple[int, int]]:
        spans: List[Tuple[int, int]] = []
        for index, char in enumerate(text):
            if char.isalnum():
                spans.append((index, index + 1))
        return spans

    def _terminal_punctuation(self, text: str) -> str:
        stripped = text.rstrip()
        if stripped and stripped[-1] in ".!?":
            return stripped[-1]
        return "."

    def _ensure_terminal_punctuation(self, text: str, punctuation: str) -> str:
        stripped = text.rstrip(" .!?")
        return f"{stripped}{punctuation}"
```

- [ ] **Step 2: Run self-edit parser tests**

Run:

```bash
python -m unittest tests.test_self_editing -v
```

Expected: all 7 tests pass.

- [ ] **Step 3: Commit parser**

Run:

```bash
git add lib/src/self_editing.py tests/__init__.py tests/test_self_editing.py
git commit -m "feat: add self-edit parser"
```

Expected: commit succeeds.

## Task 3: Add Workflow Profile Resolver

**Files:**
- Create: `tests/test_workflow_profiles.py`
- Create: `lib/src/workflow_profiles.py`

- [ ] **Step 1: Write failing profile tests**

Create `tests/test_workflow_profiles.py` with exactly:

```python
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "lib" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from workflow_profiles import WorkflowProfileResolver


class WorkflowProfileResolverTests(unittest.TestCase):
    def setUp(self):
        self.resolver = WorkflowProfileResolver()

    def test_kitty_resolves_to_terminal(self):
        profile = self.resolver.resolve({"app_id": "kitty", "class": "kitty", "title": "shell"})

        self.assertEqual(profile.name, "terminal")
        self.assertEqual(profile.paste_mode, "ctrl_shift")
        self.assertFalse(profile.allow_auto_submit)

    def test_foot_resolves_to_terminal(self):
        profile = self.resolver.resolve({"app_id": "foot", "class": "foot"})

        self.assertEqual(profile.name, "terminal")
        self.assertEqual(profile.paste_mode, "ctrl_shift")

    def test_codex_desktop_resolves_to_codex(self):
        profile = self.resolver.resolve({"app_id": "codex-desktop", "class": "codex-desktop", "title": "Codex"})

        self.assertEqual(profile.name, "codex")
        self.assertEqual(profile.paste_mode, "ctrl")
        self.assertFalse(profile.allow_auto_submit)

    def test_helium_resolves_to_browser(self):
        profile = self.resolver.resolve({"app_id": "helium", "class": "helium", "title": "YouTube - Helium"})

        self.assertEqual(profile.name, "browser")
        self.assertEqual(profile.paste_mode, "ctrl")

    def test_chromium_resolves_to_browser(self):
        profile = self.resolver.resolve({"app_id": "chromium", "class": "chromium", "title": "about:blank - Chromium"})

        self.assertEqual(profile.name, "browser")

    def test_zennotes_is_default_in_v1(self):
        profile = self.resolver.resolve({"app_id": "ZenNotes", "class": "ZenNotes", "title": "ZenNotes"})

        self.assertEqual(profile.name, "default")
        self.assertIsNone(profile.paste_mode)

    def test_unknown_app_resolves_to_default(self):
        profile = self.resolver.resolve({"app_id": "unknown-app", "class": "unknown-app", "title": "Unknown"})

        self.assertEqual(profile.name, "default")
        self.assertIsNone(profile.paste_mode)
        self.assertFalse(profile.allow_auto_submit)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run profile tests and verify they fail because the module does not exist**

Run:

```bash
python -m unittest tests.test_workflow_profiles -v
```

Expected: failure with `ModuleNotFoundError: No module named 'workflow_profiles'`.

- [ ] **Step 3: Implement workflow profiles**

Create `lib/src/workflow_profiles.py` with exactly:

```python
"""Focused-window workflow profiles for paste/action decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AppContext:
    app_id: str = ""
    window_class: str = ""
    title: str = ""
    pid: Optional[int] = None
    source: str = ""

    @classmethod
    def from_window_info(cls, window_info: Optional[Dict[str, Any]]) -> "AppContext":
        if not window_info:
            return cls()
        app_id = str(window_info.get("app_id") or window_info.get("class") or "").strip()
        window_class = str(window_info.get("class") or app_id).strip()
        title = str(window_info.get("title") or "").strip()
        pid = window_info.get("pid")
        source = str(window_info.get("source") or "").strip()
        return cls(app_id=app_id, window_class=window_class, title=title, pid=pid, source=source)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "app_id": self.app_id,
            "class": self.window_class,
            "title": self.title,
            "pid": self.pid,
            "source": self.source,
        }


@dataclass(frozen=True)
class WorkflowProfile:
    name: str
    paste_mode: Optional[str]
    allow_auto_submit: bool
    cleanup: str
    app_context: AppContext


class WorkflowProfileResolver:
    TERMINAL_IDS = {
        "kitty",
        "foot",
        "ghostty",
        "com.mitchellh.ghostty",
        "wezterm",
        "org.wezfurlong.wezterm",
        "alacritty",
        "konsole",
        "org.kde.konsole",
        "gnome-terminal",
        "org.gnome.terminal",
        "ptyxis",
        "org.gnome.ptyxis",
        "io.gitlab.ptyxis.ptyxis",
        "xfce4-terminal",
        "terminator",
        "tilix",
        "urxvt",
        "xterm",
        "st-256color",
        "sakura",
        "guake",
        "yakuake",
        "terminology",
        "cool-retro-term",
        "contour",
        "rio",
        "warp",
        "tabby",
        "hyper",
    }
    BROWSER_IDS = {"helium", "chromium", "google-chrome", "brave-browser", "firefox", "librewolf"}

    def resolve(self, window_info: Optional[Dict[str, Any]]) -> WorkflowProfile:
        context = AppContext.from_window_info(window_info)
        app_id = context.app_id.lower()
        window_class = context.window_class.lower()
        title = context.title.lower()

        if app_id in self.TERMINAL_IDS or window_class in self.TERMINAL_IDS:
            return WorkflowProfile("terminal", "ctrl_shift", False, "terminal", context)

        if app_id == "codex-desktop" or window_class == "codex-desktop" or title == "codex":
            return WorkflowProfile("codex", "ctrl", False, "codex", context)

        if app_id in self.BROWSER_IDS or window_class in self.BROWSER_IDS:
            return WorkflowProfile("browser", "ctrl", False, "default", context)

        return WorkflowProfile("default", None, False, "default", context)
```

- [ ] **Step 4: Run profile tests**

Run:

```bash
python -m unittest tests.test_workflow_profiles -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Commit profile resolver**

Run:

```bash
git add lib/src/workflow_profiles.py tests/test_workflow_profiles.py
git commit -m "feat: add workflow profile resolver"
```

Expected: commit succeeds.

## Task 4: Add Last-Transcription Payload Builder

**Files:**
- Create: `tests/test_transcription_state.py`
- Create: `lib/src/transcription_state.py`

- [ ] **Step 1: Write failing state tests**

Create `tests/test_transcription_state.py` with exactly:

```python
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "lib" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from self_editing import SelfEdit, SelfEditResult
from transcription_state import build_last_transcription_payload, review_text_from_payload
from workflow_profiles import AppContext


class TranscriptionStateTests(unittest.TestCase):
    def test_payload_contains_raw_final_processed_and_context(self):
        edit_result = SelfEditResult(
            raw_text="Open test.py. Open main.py in plaats van Open test.py.",
            final_text="Open main.py.",
            edits=[
                SelfEdit(
                    command="replace_instead_of",
                    phrase="Open main.py in plaats van Open test.py.",
                    applied=True,
                    old="Open test.py",
                    new="Open main.py",
                )
            ],
            ignored_edits=[],
        )
        payload = build_last_transcription_payload(
            text="Open main.py.",
            raw_text=edit_result.raw_text,
            final_text=edit_result.final_text,
            processed_text="Open main.py.",
            edits=edit_result.edits,
            ignored_edits=edit_result.ignored_edits,
            app_context=AppContext(app_id="kitty", window_class="kitty", title="shell", pid=123, source="niri"),
            profile="terminal",
            paste_mode="ctrl_shift",
            language="nl",
            source="recording",
            timestamp="2026-05-12T12:00:00+02:00",
        )

        self.assertEqual(payload["text"], "Open main.py.")
        self.assertEqual(payload["raw_text"], edit_result.raw_text)
        self.assertEqual(payload["final_text"], "Open main.py.")
        self.assertEqual(payload["processed_text"], "Open main.py.")
        self.assertEqual(payload["profile"], "terminal")
        self.assertEqual(payload["paste_mode"], "ctrl_shift")
        self.assertEqual(payload["app_context"]["app_id"], "kitty")
        self.assertEqual(payload["edits"][0]["command"], "replace_instead_of")

    def test_review_text_prefers_processed_then_final_then_legacy_text(self):
        self.assertEqual(review_text_from_payload({"processed_text": "processed", "final_text": "final", "text": "legacy"}), "processed")
        self.assertEqual(review_text_from_payload({"final_text": "final", "text": "legacy"}), "final")
        self.assertEqual(review_text_from_payload({"text": "legacy"}), "legacy")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run state tests and verify they fail because the module does not exist**

Run:

```bash
python -m unittest tests.test_transcription_state -v
```

Expected: failure with `ModuleNotFoundError: No module named 'transcription_state'`.

- [ ] **Step 3: Implement payload builder**

Create `lib/src/transcription_state.py` with exactly:

```python
"""Build and read last-transcription state payloads."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional


def _serialize_items(items: Optional[Iterable[Any]]) -> list:
    serialized = []
    for item in items or []:
        if is_dataclass(item):
            serialized.append(asdict(item))
        elif isinstance(item, dict):
            serialized.append(dict(item))
    return serialized


def _serialize_context(app_context: Any) -> Optional[Dict[str, Any]]:
    if app_context is None:
        return None
    if hasattr(app_context, "to_dict"):
        return app_context.to_dict()
    if is_dataclass(app_context):
        return asdict(app_context)
    if isinstance(app_context, dict):
        return dict(app_context)
    return None


def build_last_transcription_payload(
    text: str,
    *,
    raw_text: Optional[str] = None,
    final_text: Optional[str] = None,
    processed_text: Optional[str] = None,
    edits: Optional[Iterable[Any]] = None,
    ignored_edits: Optional[Iterable[Any]] = None,
    app_context: Any = None,
    profile: Optional[str] = None,
    paste_mode: Optional[str] = None,
    language: Optional[str] = None,
    source: str = "recording",
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    timestamp_value = timestamp or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    payload: Dict[str, Any] = {
        "text": text,
        "raw_text": raw_text if raw_text is not None else text,
        "final_text": final_text if final_text is not None else text,
        "processed_text": processed_text if processed_text is not None else text,
        "edits": _serialize_items(edits),
        "ignored_edits": _serialize_items(ignored_edits),
        "app_context": _serialize_context(app_context),
        "profile": profile,
        "paste_mode": paste_mode,
        "timestamp": timestamp_value,
        "language": language,
        "source": source,
    }
    return payload


def review_text_from_payload(payload: Dict[str, Any]) -> str:
    for key in ("processed_text", "final_text", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
```

- [ ] **Step 4: Run state tests**

Run:

```bash
python -m unittest tests.test_transcription_state -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit state helper**

Run:

```bash
git add lib/src/transcription_state.py tests/test_transcription_state.py
git commit -m "feat: add last transcription payload builder"
```

Expected: commit succeeds.

## Task 5: Add F1-Toggle Dictation Pipeline

**Files:**
- Create: `tests/test_recording_pipeline.py`
- Create: `lib/src/dictation_pipeline.py`

- [ ] **Step 1: Write failing pipeline tests**

Create `tests/test_recording_pipeline.py` with exactly:

```python
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "lib" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dictation_pipeline import process_toggle_dictation


class DictationPipelineTests(unittest.TestCase):
    def test_toggle_pipeline_applies_self_editing(self):
        result = process_toggle_dictation("Open test.py. Open main.py in plaats van Open test.py.")

        self.assertEqual(result.final_text, "Open main.py.")
        self.assertEqual(result.edits[0].command, "replace_instead_of")

    def test_toggle_pipeline_keeps_plain_text(self):
        result = process_toggle_dictation("Open main.py")

        self.assertEqual(result.final_text, "Open main.py")
        self.assertEqual(result.edits, [])
        self.assertEqual(result.ignored_edits, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run pipeline tests and verify they fail because the module does not exist**

Run:

```bash
python -m unittest tests.test_recording_pipeline -v
```

Expected: failure with `ModuleNotFoundError: No module named 'dictation_pipeline'`.

- [ ] **Step 3: Implement pipeline wrapper**

Create `lib/src/dictation_pipeline.py` with exactly:

```python
"""Recording-path dictation processing."""

from __future__ import annotations

try:
    from .self_editing import SelfEditParser, SelfEditResult
except ImportError:
    from self_editing import SelfEditParser, SelfEditResult


def process_toggle_dictation(raw_text: str, parser: SelfEditParser | None = None) -> SelfEditResult:
    active_parser = parser or SelfEditParser()
    return active_parser.parse(raw_text)
```

- [ ] **Step 4: Run pipeline tests**

Run:

```bash
python -m unittest tests.test_recording_pipeline -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit pipeline wrapper**

Run:

```bash
git add lib/src/dictation_pipeline.py tests/test_recording_pipeline.py
git commit -m "feat: add toggle dictation pipeline"
```

Expected: commit succeeds.

## Task 6: Integrate Workflow Profiles Into Text Injection

**Files:**
- Modify: `lib/src/text_injector.py`
- Test: `tests/test_workflow_profiles.py`

- [ ] **Step 1: Add focused-window profile tests for Niri-shaped data**

Append these tests to `WorkflowProfileResolverTests` in `tests/test_workflow_profiles.py`:

```python
    def test_niri_focused_window_data_keeps_kitty_terminal_safe(self):
        profile = self.resolver.resolve({
            "app_id": "kitty",
            "class": "kitty",
            "title": "jonathan@machine",
            "pid": 456,
            "source": "niri",
        })

        self.assertEqual(profile.name, "terminal")
        self.assertEqual(profile.paste_mode, "ctrl_shift")

    def test_unknown_niri_app_does_not_force_terminal_paste(self):
        profile = self.resolver.resolve({
            "app_id": "unknown-app",
            "class": "unknown-app",
            "title": "Unknown",
            "pid": 789,
            "source": "niri",
        })

        self.assertEqual(profile.name, "default")
        self.assertIsNone(profile.paste_mode)
```

- [ ] **Step 2: Run profile tests**

Run:

```bash
python -m unittest tests.test_workflow_profiles -v
```

Expected: all 9 tests pass.

- [ ] **Step 3: Modify imports in `lib/src/text_injector.py`**

Add this import block below the existing `require_package` import block:

```python
try:
    from .workflow_profiles import WorkflowProfileResolver
except ImportError:
    from workflow_profiles import WorkflowProfileResolver
```

- [ ] **Step 4: Add profile resolver state in `TextInjector.__init__`**

Inside `TextInjector.__init__`, after `self.config_manager = config_manager`, add:

```python
        self.profile_resolver = WorkflowProfileResolver()
        self.last_injection_result = {
            "success": False,
            "app_context": None,
            "profile": "default",
            "paste_mode": None,
        }
```

- [ ] **Step 5: Extend Niri window info**

In `_get_active_window_info`, replace the Niri return object with:

```python
                        return {
                            'app_id': app_id,
                            'class': app_id,
                            'title': window.get('title', ''),
                            'pid': window.get('pid'),
                            'source': 'niri',
                        }
```

- [ ] **Step 6: Add profile-aware auto-submit helper**

Change `_send_enter_if_auto_submit(self)` to `_send_enter_if_auto_submit(self, allow_auto_submit: bool = True)` and put this guard at the top of the method body:

```python
        if not allow_auto_submit:
            return
```

- [ ] **Step 7: Use workflow profile in `_inject_via_clipboard_and_hotkey`**

At the top of `_inject_via_clipboard_and_hotkey`, immediately after `window_info = self._get_active_window_info()`, add:

```python
            profile = self.profile_resolver.resolve(window_info)
            self.last_injection_result = {
                "success": False,
                "app_context": profile.app_context.to_dict(),
                "profile": profile.name,
                "paste_mode": profile.paste_mode,
            }
```

Replace:

```python
            is_terminal = self._is_terminal(window_info)
```

with:

```python
            is_terminal = profile.name == "terminal" or self._is_terminal(window_info)
```

Replace the auto-detect paste-mode block:

```python
                    paste_mode = self._detect_paste_mode(window_info)
```

with:

```python
                    paste_mode = profile.paste_mode or self._detect_paste_mode(window_info)
```

After paste mode is resolved, add:

```python
            self.last_injection_result["paste_mode"] = paste_mode
```

When paste succeeds, before returning, set:

```python
                self.last_injection_result["success"] = True
```

Replace:

```python
                self._send_enter_if_auto_submit()
```

with:

```python
                self._send_enter_if_auto_submit(profile.allow_auto_submit)
```

- [ ] **Step 8: Run profile tests and a syntax compile**

Run:

```bash
python -m unittest tests.test_workflow_profiles -v
python -m py_compile lib/src/text_injector.py lib/src/workflow_profiles.py
```

Expected: tests pass and compile exits 0.

- [ ] **Step 9: Commit text injection integration**

Run:

```bash
git add lib/src/text_injector.py tests/test_workflow_profiles.py
git commit -m "feat: apply workflow profiles during paste"
```

Expected: commit succeeds.

## Task 7: Integrate Self-Editing and State Into Main Recording Path

**Files:**
- Modify: `lib/main.py`
- Test: `tests/test_recording_pipeline.py`, `tests/test_transcription_state.py`

- [ ] **Step 1: Add imports to `lib/main.py`**

Below the existing imports from `paths` and before `from backend_utils import normalize_backend`, add:

```python
from dictation_pipeline import process_toggle_dictation
from transcription_state import build_last_transcription_payload
```

- [ ] **Step 2: Change `_process_audio` to self-edit only F1-toggle recordings**

In `_process_audio`, replace:

```python
                self.current_transcription = text
                self._write_last_transcription(text, language_override=self._current_language_override, source='recording')

                # Inject text
                self._inject_text(self.current_transcription)
                success = True
```

with:

```python
                edit_result = process_toggle_dictation(text)
                final_text = edit_result.final_text
                self.current_transcription = final_text

                if not final_text:
                    self._write_last_transcription(
                        final_text,
                        language_override=self._current_language_override,
                        source='recording',
                        raw_text=text,
                        final_text=final_text,
                        processed_text=final_text,
                        edits=edit_result.edits,
                        ignored_edits=edit_result.ignored_edits,
                    )
                    success = True
                    return

                injection_result = self._inject_text(final_text)
                self._write_last_transcription(
                    final_text,
                    language_override=self._current_language_override,
                    source='recording',
                    raw_text=text,
                    final_text=final_text,
                    processed_text=final_text,
                    edits=edit_result.edits,
                    ignored_edits=edit_result.ignored_edits,
                    injection_result=injection_result,
                )
                success = True
```

- [ ] **Step 3: Return injection metadata from `_inject_text`**

At the top of `_inject_text`, before the capture-mode branch, add:

```python
        default_result = {
            'success': False,
            'app_context': None,
            'profile': 'capture' if self._capture_subscriber is not None else 'default',
            'paste_mode': None,
        }
```

Inside the capture-mode branch, replace `return` with:

```python
            default_result['success'] = True
            return default_result
```

Inside the `try` block, replace:

```python
            self.text_injector.inject_text(text)
```

with:

```python
            injected = self.text_injector.inject_text(text)
            injection_result = dict(getattr(self.text_injector, 'last_injection_result', default_result))
            injection_result['success'] = bool(injected)
```

Before the end of the `try` block, add:

```python
            return injection_result
```

Inside the `except` block, after the error log, add:

```python
            return default_result
```

- [ ] **Step 4: Extend `_write_last_transcription` signature and body**

Change the function signature to:

```python
    def _write_last_transcription(
        self,
        text,
        language_override=None,
        source='recording',
        raw_text=None,
        final_text=None,
        processed_text=None,
        edits=None,
        ignored_edits=None,
        injection_result=None,
    ):
```

Replace the payload construction inside `_write_last_transcription` with:

```python
            injection_result = injection_result or {}
            payload = build_last_transcription_payload(
                text,
                raw_text=raw_text,
                final_text=final_text,
                processed_text=processed_text,
                edits=edits,
                ignored_edits=ignored_edits,
                app_context=injection_result.get('app_context'),
                profile=injection_result.get('profile'),
                paste_mode=injection_result.get('paste_mode'),
                language=language,
                source=source,
            )
```

- [ ] **Step 5: Run deterministic tests and compile main**

Run:

```bash
python -m unittest tests.test_recording_pipeline tests.test_transcription_state -v
python -m py_compile lib/main.py lib/src/dictation_pipeline.py lib/src/transcription_state.py
```

Expected: tests pass and compile exits 0.

- [ ] **Step 6: Commit main integration**

Run:

```bash
git add lib/main.py
git commit -m "feat: apply self-editing to toggle recordings"
```

Expected: commit succeeds.

## Task 8: Keep Word Review Backward-Compatible

**Files:**
- Modify: `lib/src/cli_commands.py`
- Test: `tests/test_transcription_state.py`

- [ ] **Step 1: Import review text helper**

In `lib/src/cli_commands.py`, add this import beside other local imports:

```python
try:
    from .transcription_state import review_text_from_payload
except ImportError:
    from transcription_state import review_text_from_payload
```

- [ ] **Step 2: Use review text helper in `_load_last_transcription`**

Inside `_load_last_transcription`, replace:

```python
    text = payload.get('text') if isinstance(payload, dict) else None
    if not text or not str(text).strip():
```

with:

```python
    text = review_text_from_payload(payload) if isinstance(payload, dict) else None
    if not text:
```

Keep the existing:

```python
    payload['text'] = str(text).strip()
    return payload
```

- [ ] **Step 3: Run state tests and compile CLI commands**

Run:

```bash
python -m unittest tests.test_transcription_state -v
python -m py_compile lib/src/cli_commands.py
```

Expected: tests pass and compile exits 0.

- [ ] **Step 4: Commit review compatibility**

Run:

```bash
git add lib/src/cli_commands.py
git commit -m "feat: preserve word review for self-edited transcripts"
```

Expected: commit succeeds.

## Task 9: Run Full Local Verification

**Files:**
- Verify: all changed Python files and tests.

- [ ] **Step 1: Run full deterministic test suite**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Compile touched runtime modules**

Run:

```bash
python -m py_compile \
  lib/src/self_editing.py \
  lib/src/workflow_profiles.py \
  lib/src/transcription_state.py \
  lib/src/dictation_pipeline.py \
  lib/src/text_injector.py \
  lib/src/cli_commands.py \
  lib/main.py
```

Expected: command exits 0 with no output.

- [ ] **Step 3: Verify CLI help still loads**

Run:

```bash
./bin/hyprwhspr --help >/tmp/hyprwhspr-help.txt
./bin/hyprwhspr words --help >/tmp/hyprwhspr-words-help.txt
```

Expected: both commands exit 0.

- [ ] **Step 4: Commit verification-only fixes if needed**

If any verification command exposes a small integration issue, fix it with the narrowest patch and commit:

```bash
git add \
  lib/src/self_editing.py \
  lib/src/workflow_profiles.py \
  lib/src/transcription_state.py \
  lib/src/dictation_pipeline.py \
  lib/src/text_injector.py \
  lib/src/cli_commands.py \
  lib/main.py \
  tests
git commit -m "fix: stabilize self-editing workflow integration"
```

Expected: no commit is needed if Steps 1-3 pass.

## Task 10: Manual Smoke Test On Jonathan's Machine

**Files:**
- Verify: user service and local desktop behavior.

- [ ] **Step 1: Restart the local user service**

Run:

```bash
systemctl --user restart hyprwhspr
systemctl --user is-active hyprwhspr
```

Expected: `active`.

- [ ] **Step 2: Smoke test terminal-safe paste in `kitty`**

Focus a `kitty` window and dictate:

```text
Open test punt py. Open main punt py in plaats van Open test punt py.
```

Expected pasted text:

```text
Open main.py.
```

Expected behavior: paste happens with terminal-safe `Ctrl+Shift+V`; no Enter is sent.

- [ ] **Step 3: Smoke test terminal-safe paste in `foot`**

Focus a `foot` window and dictate:

```text
Start de service opnieuw. Corrigeer start de service opnieuw naar systemctl --user restart hyprwhspr.
```

Expected pasted text:

```text
systemctl --user restart hyprwhspr.
```

Expected behavior: paste happens with terminal-safe `Ctrl+Shift+V`; no Enter is sent.

- [ ] **Step 4: Smoke test Codex Desktop paste**

Focus Codex Desktop and dictate:

```text
Maak een korte checklist. Nee wacht maak een korte test checklist.
```

Expected pasted text:

```text
maak een korte test checklist.
```

Expected behavior: normal paste; no auto-submit.

- [ ] **Step 5: Inspect last-transcription state**

Run:

```bash
python -m json.tool ~/.config/hyprwhspr/last_transcription.json
```

Expected: JSON includes `raw_text`, `final_text`, `processed_text`, `edits`, `ignored_edits`, `app_context`, `profile`, `paste_mode`, `timestamp`, `language`, and `source`.

- [ ] **Step 6: Verify word review still opens**

Run:

```bash
./bin/hyprwhspr words review
```

Expected: fuzzel or rofi picker opens using the final/processed transcript text.

- [ ] **Step 7: Commit smoke-test fixes if needed**

If smoke tests expose a machine-specific integration issue, fix only that issue and commit:

```bash
git add \
  lib/src/self_editing.py \
  lib/src/workflow_profiles.py \
  lib/src/transcription_state.py \
  lib/src/dictation_pipeline.py \
  lib/src/text_injector.py \
  lib/src/cli_commands.py \
  lib/main.py \
  tests
git commit -m "fix: handle local self-editing smoke test"
```

Expected: no commit is needed if Steps 1-6 pass.

## Final Acceptance Checklist

- [ ] `python -m unittest discover -s tests -v` passes.
- [ ] `python -m py_compile` passes for all touched runtime modules.
- [ ] F1-toggle dictations self-edit before paste.
- [ ] `delete/verwijder alles wat ik net gezegd heb` clears only the current buffer.
- [ ] `verwijder de laatste zin` and `verwijder het laatste woord` affect only the current buffer.
- [ ] `corrigeer <old> naar <new>` and `<new> in plaats van <old>` replace only the current buffer text.
- [ ] `nee wacht <new text>` replaces the previous sentence inside the current buffer.
- [ ] `kitty` and `foot` resolve to terminal profile through Niri-style focused-window data.
- [ ] Terminal profile uses `ctrl_shift` and blocks auto-submit.
- [ ] Codex Desktop resolves to Codex profile and blocks auto-submit in V1.
- [ ] `last_transcription.json` preserves raw, final, processed text, edits, app context, profile, paste mode, timestamp, language, and source.
- [ ] `hyprwhspr words review` still works with extended state.
- [ ] Continuous and long-form paths are not given destructive desktop-editing behavior.
