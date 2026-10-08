"""A small, explicitly specified deterministic random stream for reproducible games."""

from __future__ import annotations

from dataclasses import dataclass
from typing import MutableSequence, TypeVar


_MASK = (1 << 64) - 1
_GAMMA = 0x9E3779B97F4A7C15
_MIX_A = 0xBF58476D1CE4E5B9
_MIX_B = 0x94D049BB133111EB
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RandomStreamSnapshot:
    seed: int
    state: int
    draw_count: int


class FixedSeedRandom:
    """SplitMix64 stream. It is deterministic, not intended for secrets."""

    def __init__(self, seed: int) -> None:
        if not isinstance(seed, int):
            raise TypeError("seed must be an integer")
        self._seed = seed & _MASK
        self._state = self._seed
        self._draw_count = 0

    @classmethod
    def restore(cls, snapshot: RandomStreamSnapshot) -> FixedSeedRandom:
        stream = cls(snapshot.seed)
        stream._state = snapshot.state & _MASK
        stream._draw_count = snapshot.draw_count
        return stream

    def snapshot(self) -> RandomStreamSnapshot:
        return RandomStreamSnapshot(self._seed, self._state, self._draw_count)

    def _next_u64(self) -> int:
        self._state = (self._state + _GAMMA) & _MASK
        value = self._state
        value = ((value ^ (value >> 30)) * _MIX_A) & _MASK
        value = ((value ^ (value >> 27)) * _MIX_B) & _MASK
        self._draw_count += 1
        return (value ^ (value >> 31)) & _MASK

    def randbelow(self, stop: int) -> int:
        if stop <= 0:
            raise ValueError("stop must be positive")
        limit = (1 << 64) - ((1 << 64) % stop)
        while True:
            value = self._next_u64()
            if value < limit:
                return value % stop

    def choice(self, values: tuple[T, ...] | list[T]) -> T:
        if not values:
            raise IndexError("cannot choose from an empty sequence")
        return values[self.randbelow(len(values))]

    def shuffle(self, values: MutableSequence[T]) -> None:
        for index in range(len(values) - 1, 0, -1):
            other = self.randbelow(index + 1)
            values[index], values[other] = values[other], values[index]

