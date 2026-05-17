"""Fixed-kernel RNG helpers."""

from __future__ import annotations


def next_rng(value: int) -> int:
    x = value or 1
    x ^= (x << 13) & 0xFFFFFFFF
    x ^= (x >> 17) & 0xFFFFFFFF
    x ^= (x << 5) & 0xFFFFFFFF
    return x & 0xFFFFFFFF
