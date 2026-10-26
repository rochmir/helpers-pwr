"""Stan narzędzi testowych admina: sesje gry „uzbrojone” na wygraną (pamięć procesu, 1 worker)."""
from __future__ import annotations

import threading

_lock = threading.Lock()
_armed: set[str] = set()


def arm(sid: str) -> None:
    with _lock:
        _armed.add(sid)


def is_armed(sid: str) -> bool:
    with _lock:
        return sid in _armed


def consume_arm(sid: str) -> bool:
    """Zwraca True i zdejmuje uzbrojenie, jeśli sesja była uzbrojona."""
    with _lock:
        if sid in _armed:
            _armed.discard(sid)
            return True
        return False


def clear() -> None:
    with _lock:
        _armed.clear()
