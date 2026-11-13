"""Geometría de dominio: cajas en coordenadas normalizadas [0,1], independientes de la resolución."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Size:
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("el tamaño debe ser positivo")


@dataclass(frozen=True, slots=True)
class BBox:
    """Caja xyxy normalizada. Permite una pequeña tolerancia fuera de [0,1] (objetos en el borde)."""

    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        if not (self.x2 > self.x1 and self.y2 > self.y1):
            raise ValueError(f"caja degenerada: {self}")
        if min(self.x1, self.y1) < -0.05 or max(self.x2, self.y2) > 1.05:
            raise ValueError(f"caja fuera de rango normalizado: {self}")

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def foot_point(self) -> tuple[float, float]:
        """Punto de apoyo (centro inferior): se usa para decidir pertenencia a zonas."""
        return ((self.x1 + self.x2) / 2, self.y2)

    def intersection(self, other: BBox) -> float:
        ix = max(0.0, min(self.x2, other.x2) - max(self.x1, other.x1))
        iy = max(0.0, min(self.y2, other.y2) - max(self.y1, other.y1))
        return ix * iy

    def iou(self, other: BBox) -> float:
        inter = self.intersection(other)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def ioa(self, other: BBox) -> float:
        """Fracción de ESTA caja contenida en ``other``."""
        return self.intersection(other) / self.area if self.area > 0 else 0.0

    def to_pixels(self, size: Size) -> tuple[int, int, int, int]:
        return (round(self.x1 * size.width), round(self.y1 * size.height),
                round(self.x2 * size.width), round(self.y2 * size.height))

    def touches_border(self, margin: float = 0.01) -> bool:
        return self.x1 <= margin or self.y1 <= margin or self.x2 >= 1 - margin or self.y2 >= 1 - margin


def point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """Ray casting; polígono en coordenadas normalizadas."""
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside
