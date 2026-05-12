# Self-Editing Workflow Router Design

Date: 2026-05-12
Status: Approved for specification, not yet approved for implementation

## Goal

Make hyprwhspr substantially better for Jonathan's local Niri + terminal + Codex workflow by turning short F1-toggle dictations into self-editing, context-aware text actions.

The main workflow should feel like natural speech:

1. Start dictation with F1.
2. Speak the intended text.
3. Correct yourself inside the same utterance when needed.
4. Stop dictation with F1.
5. hyprwhspr applies safe inline edits before anything is pasted.
6. hyprwhspr chooses the right paste behavior for the focused app.

## Local Context

The design is specific to the current local setup:

- Compositor: Niri on Wayland.
- Common targets: `kitty`, `foot`, Codex Desktop, browser/form inputs.
- Current shortcuts: F1 primary, F2 cancel.
- Current backend: Groq REST API with `whisper-large-v3`.
- Existing personal correction data: `word_overrides`, `banned_words`, and `hyprwhspr words review`.
- Existing local fix: Niri focused-window detection is already used to keep terminal paste on `Ctrl+Shift+V`.
- Observed Niri app ids during design: `helium`, `codex-desktop`, `ZenNotes`, and `chromium`.

## V1 Scope

V1 is the Self-Editing Workflow Router:

- Inline self-editing for current F1-toggle dictations.
- A dictation buffer that is edited before paste.
- Niri-aware app profiles for paste/action decisions.
- Terminal-safe paste for `kitty` and `foot`.
- Codex-friendly paste behavior for Codex Desktop.
- Extended last-transcription state with raw text, final text, edits, app context, profile, and paste mode.
- Improved review visibility for the existing word-learning flow.

## Non-Goals

V1 does not implement:

- Continuous-mode self-editing.
- Long-form dictation editing.
- Voice commands that manipulate already-pasted desktop text.
- Blind deletion from terminal, Codex, browser, or any focused app.
- AI-driven rewriting or summarization.
- Zennotes capture automation.
- Provider switching or transcription backend changes.

These can become later specs after the F1-toggle path is reliable.

## User-Facing Behavior

Self-edit commands work only on the current dictation buffer. They do not act on already-pasted text.

Example:

```text
Maak een bestand test punt py nee wacht maak een bestand main punt py
```

Final buffer:

```text
Maak een bestand main.py
```

Example:

```text
Start de service opnieuw. Corrigeer start de service opnieuw naar systemctl --user restart hyprwhspr.
```

Final buffer:

```text
systemctl --user restart hyprwhspr.
```

## Self-Edit Command Grammar

V1 supports a small deterministic grammar. The parser should prefer doing nothing over making a destructive edit when a command is ambiguous.

| Spoken pattern | Effect |
| --- | --- |
| `delete alles wat ik net gezegd heb` | Clear the current dictation buffer. |
| `verwijder alles wat ik net gezegd heb` | Clear the current dictation buffer. |
| `verwijder de laatste zin` | Remove the last sentence from the current buffer. |
| `verwijder het laatste woord` | Remove the last word from the current buffer. |
| `corrigeer <old> naar <new>` | Replace the last matching `<old>` span with `<new>`. |
| `<new> in plaats van <old>` | Replace the last matching `<old>` span with `<new>`. |
| `nee wacht <new text>` | Remove the previous sentence and append `<new text>`. |

### Matching Rules

- Replacement commands operate on the latest matching span in the buffer.
- Matching is case-insensitive.
- Punctuation differences should not block obvious phrase matches.
- If `<old>` cannot be found, the command is recorded as ignored and no buffer edit is made.
- If a command phrase appears inside a quoted or literal context in a later version, that later version should provide an escape mechanism. V1 does not need literal escape syntax.

## Processing Order

The self-edit parser runs before normal post-processing:

```text
raw transcript
  -> light command normalization
  -> self-edit parser
  -> word_overrides and banned_words
  -> app profile cleanup
  -> paste/action
  -> last-transcription state
```

This order keeps edit commands understandable before user word replacements mutate the text.

## Components

### Window Context

Provide a small context object for the focused app:

```json
{
  "app_id": "kitty",
  "title": "...",
  "pid": 12345,
  "source": "niri"
}
```

Niri is the primary source on this machine. Existing Hyprland, XWayland, and AT-SPI fallbacks may remain as compatibility paths.

### Workflow Profile Resolver

Map window context to a profile:

| App context | Profile |
| --- | --- |
| `kitty` | `terminal` |
| `foot` | `terminal` |
| `codex-desktop` or title `Codex` | `codex` |
| `helium`, `chromium`, or other browser-like app id/title | `browser` |
| `ZenNotes` | `default` in V1 |
| Anything else | `default` |

Profiles determine paste mode, auto-submit policy, and profile-specific cleanup.

### Dictation Buffer

The buffer is an internal representation of one F1-toggle recording. It tracks:

- Raw transcript.
- Current editable text.
- Applied edit commands.
- Ignored edit commands.

The buffer exists only before paste for V1.

### Self-Edit Parser

The parser consumes the raw transcript and emits:

```json
{
  "final_text": "...",
  "edits": [
    {
      "command": "corrigeer",
      "old": "start de service opnieuw",
      "new": "systemctl --user restart hyprwhspr",
      "applied": true
    }
  ],
  "ignored_edits": []
}
```

The parser is deterministic and local. It should not call a language model in V1.

### Transcript Pipeline

After self-editing, the existing cleanup pipeline applies:

- `word_overrides`
- `banned_words`
- filler-word filtering if enabled
- symbol replacements
- optional `post_transcription_hook`

The design should preserve the user's existing correction workflow and config.

### Action Executor

The executor receives final text plus the resolved profile and performs the action:

- Paste via clipboard and hotkey.
- Leave text on clipboard if paste fails.
- Never auto-submit in terminal.
- Record enough state to debug what happened.

## App Profiles

### Terminal Profile

Targets: `kitty`, `foot`.

Behavior:

- Use `Ctrl+Shift+V`.
- Disable auto-submit.
- Remove trailing newlines before paste.
- Prefer conservative cleanup.
- Never run blind undo/delete operations against the terminal.

This profile protects the CLI workflow where accidental Enter or destructive edits are high risk.

### Codex Profile

Targets: Codex Desktop.

Behavior:

- Use normal paste.
- Disable auto-submit in V1.
- Preserve paragraph-level prompt text.
- Allow prompt-friendly cleanup, but avoid adding wrappers by default.

This keeps Codex dictation useful without making the app submit prompts unexpectedly.

### Browser Profile

Targets: `helium`, `chromium`, and browser-like app ids/titles.

Behavior:

- Use normal paste.
- Disable auto-submit in V1.
- Keep current default cleanup behavior.

### Default Profile

Targets: unknown apps and `ZenNotes` in V1.

Behavior:

- Use current auto-detected paste mode.
- Disable auto-submit unless explicitly configured by the user.
- Do not apply app-specific cleanup.

## Last-Transcription State

Extend `last_transcription.json` so review and debugging can explain what happened.

V1 state shape:

```json
{
  "raw_text": "...",
  "final_text": "...",
  "processed_text": "...",
  "edits": [],
  "ignored_edits": [],
  "app_context": {
    "app_id": "kitty",
    "title": "...",
    "pid": 12345,
    "source": "niri"
  },
  "profile": "terminal",
  "paste_mode": "ctrl_shift",
  "timestamp": "2026-05-12T12:00:00+02:00"
}
```

The existing `hyprwhspr words review` flow should continue to work. It can use `final_text` or `processed_text` for review while still showing raw text for diagnosis.

## Error Handling

V1 must fail conservatively:

| Situation | Behavior |
| --- | --- |
| Niri focused-window query fails | Use existing fallback/default detection. |
| App profile is unknown | Use default profile. |
| Self-edit command is ambiguous | Do not apply the edit; record it as ignored if detected. |
| Replacement target is not found | Do not edit the buffer; record ignored edit. |
| Paste hotkey fails | Leave final text on clipboard and log profile/context. |
| Hook/correction step fails | Preserve the text from the prior successful stage. |
| Target looks terminal-like | Terminal safety wins: no auto-submit, no destructive desktop edit. |
| Review picker is unavailable | Notify/log clearly; do not mutate config. |

## Testing Strategy

Tests should focus on deterministic logic and the previous CLI paste regression.

### Unit Tests

- Self-edit parser:
  - clears buffer for `delete alles wat ik net gezegd heb`
  - removes last sentence
  - removes last word
  - applies `corrigeer <old> naar <new>`
  - applies `<new> in plaats van <old>`
  - applies `nee wacht <new text>`
  - ignores missing replacement targets
- Profile resolver:
  - `kitty` resolves to `terminal`
  - `foot` resolves to `terminal`
  - Codex Desktop resolves to `codex`
  - unknown app resolves to `default`
- Paste policy:
  - terminal profile uses `ctrl_shift`
  - terminal profile disables auto-submit
  - Codex profile disables auto-submit in V1
- Last-transcription state:
  - includes raw text, final text, edits, app context, profile, paste mode, and timestamp

### Regression Tests

- Niri focused-window data with `app_id=kitty` must resolve to terminal paste.
- Unknown Niri app data must not force terminal paste.
- A failed self-edit command must not erase text.

### Manual Smoke Tests On This Machine

- Dictate into `kitty` and verify `Ctrl+Shift+V` behavior.
- Dictate into `foot` and verify `Ctrl+Shift+V` behavior.
- Dictate into Codex Desktop and verify normal paste without auto-submit.
- Dictate into a browser input and verify default paste.
- Use `hyprwhspr words review` after a self-edited dictation and confirm review still works.

## Rollout Plan

The implementation should be split so each part can be verified independently:

1. Add self-edit parser with unit tests.
2. Add workflow profile resolver with unit tests.
3. Extend last-transcription state.
4. Integrate parser before existing cleanup.
5. Integrate profile resolver with paste policy.
6. Run manual smoke tests on Niri, `kitty`, `foot`, Codex Desktop, and browser.

## Acceptance Criteria

- F1-toggle dictations can self-correct before paste.
- Supported self-edit commands work only on the current dictation buffer.
- Terminal targets never receive auto-submit in V1.
- `kitty` and `foot` resolve to terminal-safe paste through Niri context.
- Codex Desktop receives normal paste without auto-submit.
- Existing `word_overrides`, `banned_words`, and `words review` behavior still work.
- `last_transcription.json` gives enough context to understand raw versus final output.
- No implementation touches continuous-mode desktop text deletion in V1.
