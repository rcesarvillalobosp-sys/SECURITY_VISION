"""Tiempos por etapa del análisis (ventana deslizante por tiempo, percentiles) para perfilar el worker.

Coste despreciable: una inserción en un ``deque`` por etapa y fotograma. Los percentiles se calculan solo
cuando Prometheus pide las métricas, sobre los últimos ``window_seconds`` (por defecto 60 s): así una
prueba de carga mide su propio nivel y no arrastra el anterior.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class StageTimings:
    def __init__(self, window_seconds: float = 60.0, max_samples: int = 50_000,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.window_seconds = window_seconds
        self._max = max_samples
        self._clock = clock
        self._data: dict[str, deque[tuple[float, float]]] = {}
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def add(self, stage: str, ms: float) -> None:
        with self._lock:
            d = self._data.get(stage)
            if d is None:
                d = self._data[stage] = deque(maxlen=self._max)
            d.append((self._clock(), ms))
            self._counts[stage] = self._counts.get(stage, 0) + 1

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.add(stage, (time.perf_counter() - t0) * 1000)

    def snapshot(self) -> dict[str, dict[str, float]]:
        """{etapa: {p50, p95, max, mean, count, n}} de la ventana (``count`` = total histórico)."""
        cutoff = self._clock() - self.window_seconds
        with self._lock:
            for d in self._data.values():
                while d and d[0][0] < cutoff:
                    d.popleft()
            items = {k: sorted(ms for _, ms in v) for k, v in self._data.items() if v}
            counts = dict(self._counts)
        out = {}
        for k, v in items.items():
            n = len(v)
            out[k] = {"p50": v[n // 2], "p95": v[min(n - 1, int(0.95 * (n - 1) + 0.5))], "max": v[-1],
                      "mean": sum(v) / n, "count": counts.get(k, n), "n": n}
        return out
