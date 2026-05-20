"""File-based audio level source for the mic OSD."""

from __future__ import annotations

import math
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

    if not math.isfinite(value):
        return None

    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value
