"""Cola acotada "el más reciente gana": desacopla captura y análisis con backpressure.

La captura nunca se bloquea: si el consumidor va lento se descarta el fotograma más
antiguo (y se cuenta). El análisis siempre obtiene el fotograma más reciente, nunca vídeo atrasado.
"""

from __future__ import annotations

import threading
from collections import deque


class FrameSlot[T]:
    def __init__(self, capacity: int = 1) -> None:
        if capacity < 1:
            raise ValueError("capacity >= 1")
        self._items: deque[T] = deque()
        self._capacity = capacity
        self._cond = threading.Condition()
        self._closed = False
        self.put_count = 0
        self.dropped = 0

    def put(self, item: T) -> None:
        with self._cond:
            if self._closed:
                return
            if len(self._items) >= self._capacity:
                self._items.popleft()
                self.dropped += 1
            self._items.append(item)
            self.put_count += 1
            self._cond.notify()

    def get_latest(self, timeout: float | None = None) -> T | None:
        """Devuelve el elemento más reciente y descarta (contando) los anteriores no consumidos."""
        with self._cond:
            if not self._items and not self._closed:
                self._cond.wait(timeout)
            if not self._items:
                return None
            latest = self._items.pop()
            self.dropped += len(self._items)
            self._items.clear()
            return latest

    def peek_latest(self) -> T | None:
        with self._cond:
            return self._items[-1] if self._items else None

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def __len__(self) -> int:
        with self._cond:
            return len(self._items)
