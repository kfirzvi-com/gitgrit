from __future__ import annotations

from dataclasses import dataclass

NODE_W, NODE_H = 170, 58


@dataclass(frozen=True)
class MapNode:
    """A stack's box on the dashboard's stack map, with its projects counted
    by health."""

    stack: object
    counts: object  # ProjectHealthCounts
    x: int
    y: int

    @property
    def cx(self):
        return self.x + NODE_W / 2
