"""Identificadores UUIDv7 (RFC 9562): ordenables por tiempo, buenos para índices B-tree."""

from __future__ import annotations

import os
import time
from uuid import UUID


def uuid7() -> UUID:
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # versión 7
    value |= ((rand >> 62) & 0xFFF) << 64  # rand_a (12 bits)
    value |= 0b10 << 62  # variante RFC 4122
    value |= rand & ((1 << 62) - 1)  # rand_b (62 bits)
    return UUID(int=value)
