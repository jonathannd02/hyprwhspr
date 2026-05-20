"""Best-effort positioning helpers for the mic OSD."""

from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time
from typing import Optional, Tuple


@dataclass(frozen=True)
class CaretRect:
    """Screen-space caret bounds."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class MonitorGeometry:
    """Screen-space monitor bounds."""

    x: int
    y: int
    width: int
    height: int


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
    if osd_width + (2 * margin) > screen_width:
        return None
    if not _is_finite_rect(caret):
        return None
    if caret.width < 0 or caret.height <= 0:
        return None

    caret_center_x = caret.x + (caret.width / 2)
    if caret.x < 0 or caret.x + caret.width > screen_width:
        return None
    if caret.y < 0 or caret.y + caret.height > screen_height:
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


def compute_osd_position_for_monitors(
    caret: Optional[CaretRect],
    monitors: list[MonitorGeometry],
    osd_width: int,
    osd_height: int,
    *,
    fixed_x: int = 10,
    fixed_y: int = 10,
    gap: int = 8,
    margin: int = 10,
) -> Optional[tuple[int, int, int]]:
    """Return monitor index plus monitor-local OSD coordinates for a global caret."""
    if caret is None:
        return None
    if not _is_finite_rect(caret) or caret.width < 0 or caret.height <= 0:
        return None

    caret_right = caret.x + caret.width
    caret_bottom = caret.y + caret.height

    for index, monitor in enumerate(monitors):
        if monitor.width <= 0 or monitor.height <= 0:
            continue

        if (
            caret.x < monitor.x
            or caret_right > monitor.x + monitor.width
            or caret.y < monitor.y
            or caret_bottom > monitor.y + monitor.height
        ):
            continue

        local_caret = CaretRect(
            x=caret.x - monitor.x,
            y=caret.y - monitor.y,
            width=caret.width,
            height=caret.height,
        )
        position = compute_osd_position(
            local_caret,
            screen_width=monitor.width,
            screen_height=monitor.height,
            osd_width=osd_width,
            osd_height=osd_height,
            fixed_x=fixed_x,
            fixed_y=fixed_y,
            gap=gap,
            margin=margin,
        )
        if position is None:
            return None
        x, y = position
        return (index, x, y)

    return None


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


def _deadline_expired(deadline: float) -> bool:
    return time.monotonic() >= deadline


def _remaining_time(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _find_focused_text_accessible(Atspi, deadline: float):
    stack = []
    try:
        if _deadline_expired(deadline):
            return None
        desktop = Atspi.get_desktop(0)
        if _deadline_expired(deadline):
            return None
        child_count = desktop.get_child_count()
        for i in range(child_count):
            if _deadline_expired(deadline):
                return None
            child = desktop.get_child_at_index(i)
            if child is not None:
                stack.append((child, 0))
    except Exception:
        return None

    while stack:
        if _deadline_expired(deadline):
            return None
        accessible, depth = stack.pop()
        try:
            states = accessible.get_state_set()
            if _deadline_expired(deadline):
                return None
            if states and states.contains(Atspi.StateType.FOCUSED):
                if _deadline_expired(deadline):
                    return None
                text_iface = accessible.get_text_iface()
                if _deadline_expired(deadline):
                    return None
                if text_iface is not None:
                    return text_iface
        except Exception:
            pass

        if depth >= 8:
            continue

        try:
            if _deadline_expired(deadline):
                return None
            child_count = accessible.get_child_count()
        except Exception:
            continue
        for index in range(child_count - 1, -1, -1):
            if _deadline_expired(deadline):
                return None
            try:
                child = accessible.get_child_at_index(index)
            except Exception:
                child = None
            if child is not None:
                stack.append((child, depth + 1))

    return None


def _caret_rect_from_text_iface(Atspi, text_iface, deadline: float) -> Optional[CaretRect]:
    if _deadline_expired(deadline):
        return None

    offset = text_iface.get_caret_offset()
    if _deadline_expired(deadline) or offset < 0:
        return None

    rect = text_iface.get_character_extents(offset, Atspi.CoordType.SCREEN)
    if _deadline_expired(deadline):
        return None

    caret = CaretRect(
        x=float(rect.x),
        y=float(rect.y),
        width=float(rect.width),
        height=float(rect.height),
    )
    if not _is_finite_rect(caret) or caret.width < 0 or caret.height <= 0:
        return None
    return caret


def _find_focused_caret_rect(Atspi, deadline: float, max_depth: int = 32) -> Optional[CaretRect]:
    stack = []
    try:
        if _deadline_expired(deadline):
            return None
        desktop = Atspi.get_desktop(0)
        child_count = desktop.get_child_count()
        for i in range(child_count):
            if _deadline_expired(deadline):
                return None
            child = desktop.get_child_at_index(i)
            if child is not None:
                stack.append((child, 0))
    except Exception:
        return None

    while stack:
        if _deadline_expired(deadline):
            return None
        accessible, depth = stack.pop()

        try:
            states = accessible.get_state_set()
            focused = states and states.contains(Atspi.StateType.FOCUSED)
        except Exception:
            focused = False

        if focused:
            try:
                text_iface = accessible.get_text_iface()
                if text_iface is not None:
                    caret = _caret_rect_from_text_iface(Atspi, text_iface, deadline)
                    if caret is not None:
                        return caret
            except Exception:
                pass

        if depth >= max_depth:
            continue

        try:
            if _deadline_expired(deadline):
                return None
            child_count = accessible.get_child_count()
        except Exception:
            continue
        for index in range(child_count - 1, -1, -1):
            if _deadline_expired(deadline):
                return None
            try:
                child = accessible.get_child_at_index(index)
            except Exception:
                child = None
            if child is not None:
                stack.append((child, depth + 1))

    return None


def get_focused_caret_rect(timeout: float = 0.5) -> Optional[CaretRect]:
    """Return focused caret bounds from AT-SPI, or None when unavailable."""
    timeout = max(0.0, timeout)
    deadline = time.monotonic() + timeout
    if not _ATSPI_LOCK.acquire(timeout=timeout):
        return None
    try:
        if _deadline_expired(deadline):
            return None

        Atspi = _load_atspi(timeout=_remaining_time(deadline))
        if Atspi is None:
            return None

        if _deadline_expired(deadline):
            return None

        return _find_focused_caret_rect(Atspi, deadline)
    except Exception:
        return None
    finally:
        _ATSPI_LOCK.release()
