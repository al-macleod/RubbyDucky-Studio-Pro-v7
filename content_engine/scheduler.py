import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class IntervalScheduler:
    interval_seconds: int
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self):
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero")
        self._next_run = self.clock()

    def due(self) -> bool:
        now = self.clock()
        if now < self._next_run:
            return False
        self._next_run = now + self.interval_seconds
        return True
